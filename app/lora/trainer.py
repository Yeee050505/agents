import json
import os
import sys
import traceback
from pathlib import Path
from typing import Optional

from app.utils.logger import logger
from app.lora.adapter_manager import adapter_manager, ADAPTERS_DIR

# ----------- 依赖懒加载 -----------

_LORA_READY = False
_LORA_ERROR = ""


def _check_deps():
    global _LORA_READY, _LORA_ERROR
    if _LORA_READY:
        return True
    if _LORA_ERROR:
        raise RuntimeError(_LORA_ERROR)
    try:
        import torch
        import peft
        import transformers
        import accelerate

        _LORA_READY = True
        return True
    except ImportError as e:
        _LORA_ERROR = f"LoRA dependencies missing: {e}. Install: pip install peft accelerate"
        raise RuntimeError(_LORA_ERROR)


def _get_device():
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


# ----------- Trainer -----------


class LoRATrainer:
    def __init__(self):
        self._device = _get_device()
        self._model = None
        self._tokenizer = None
        self._peft_model = None
        self._loaded_adapter: Optional[str] = None
        self._base_model_name = "Qwen/Qwen2.5-3B"

    @property
    def device(self):
        return self._device

    @property
    def base_model(self):
        return self._base_model_name

    def train(
        self,
        dataset: list[dict],
        adapter_name: str,
        base_model: str = "",
        num_epochs: int = 3,
        learning_rate: float = 2e-4,
        r: int = 8,
        lora_alpha: int = 32,
        lora_dropout: float = 0.05,
    ) -> dict:
        _check_deps()
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, Trainer
        from peft import LoraConfig, get_peft_model, TaskType

        if base_model:
            self._base_model_name = base_model

        logger.info(f"LoRA training on {self._device}: {adapter_name}, base={self._base_model_name}")

        # 1. 格式化数据集
        if not dataset:
            raise ValueError("Dataset is empty")
        texts = []
        for item in dataset:
            if "instruction" in item and "output" in item:
                texts.append(f"{item['instruction']}\n{item['output']}")
            elif "input" in item and "output" in item:
                texts.append(f"{item['input']}\n{item['output']}")
            elif "text" in item:
                texts.append(item["text"])
            else:
                texts.append(str(item))

        # 2. 加载模型和 tokenizer
        logger.info(f"Loading base model: {self._base_model_name}")
        tokenizer = AutoTokenizer.from_pretrained(
            self._base_model_name, trust_remote_code=True, use_fast=False
        )
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        model = AutoModelForCausalLM.from_pretrained(
            self._base_model_name,
            trust_remote_code=True,
            torch_dtype=torch.bfloat16,
            device_map=None,
        )
        if self._device == "cuda":
            model = model.to("cuda")
        model.train()

        # 3. LoRA 配置
        lora_config = LoraConfig(
            task_type=TaskType.CAUSAL_LM,
            r=r,
            lora_alpha=lora_alpha,
            lora_dropout=lora_dropout,
            target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],
        )
        peft_model = get_peft_model(model, lora_config)
        peft_model.print_trainable_parameters()

        # 4. Tokenize
        encodings = tokenizer(
            texts, truncation=True, padding=True, max_length=512, return_tensors="pt"
        )

        class TextDataset(torch.utils.data.Dataset):
            def __init__(self, encodings):
                self.encodings = encodings
                self.labels = encodings["input_ids"].clone()

            def __getitem__(self, i):
                return {
                    "input_ids": self.encodings["input_ids"][i],
                    "attention_mask": self.encodings["attention_mask"][i],
                    "labels": self.labels[i],
                }

            def __len__(self):
                return len(self.encodings.input_ids)

        train_dataset = TextDataset(encodings)

        # 5. 训练配置
        output_dir = ADAPTERS_DIR / adapter_name
        training_args = TrainingArguments(
            output_dir=str(output_dir),
            num_train_epochs=num_epochs,
            per_device_train_batch_size=2,
            gradient_accumulation_steps=4,
            learning_rate=learning_rate,
            logging_steps=10,
            save_strategy="epoch",
            save_total_limit=1,
            remove_unused_columns=False,
            report_to="none",
            dataloader_pin_memory=False,
            bf16=self._device == "cuda",
        )

        trainer = Trainer(
            model=peft_model,
            args=training_args,
            train_dataset=train_dataset,
            processing_class=tokenizer,
        )

        # 6. 训练
        logger.info("Starting LoRA training...")
        result = trainer.train()

        # 7. 保存 adapter
        peft_model.save_pretrained(str(output_dir))
        tokenizer.save_pretrained(str(output_dir))

        # 写入训练元信息（单独文件，不覆盖 PEFT 的 adapter_config.json）
        meta = {
            "base_model_name_or_path": self._base_model_name,
            "r": r,
            "lora_alpha": lora_alpha,
            "lora_dropout": lora_dropout,
            "num_epochs": num_epochs,
            "learning_rate": learning_rate,
            "dataset_size": len(dataset),
            "steps": int(result.global_step) if hasattr(result, "global_step") else 0,
            "device": self._device,
        }
        (output_dir / "train_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 释放显存
        del model, peft_model, trainer
        import torch
        if self._device == "cuda":
            torch.cuda.empty_cache()

        self._loaded_adapter = None
        self._peft_model = None
        self._model = None
        self._tokenizer = None

        logger.info(f"LoRA training complete: {adapter_name}")
        return {"adapter_name": adapter_name, **meta}

    def infer(self, adapter_name: str, text: str, max_length: int = 256) -> str:
        _check_deps()
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import PeftModel

        adapter_path = adapter_manager.get_adapter_path(adapter_name)
        if not adapter_path:
            raise ValueError(f"Adapter not found: {adapter_name}")

        # 加载 base model（如已加载且相同，跳过）
        if self._model is None or self._loaded_adapter != adapter_name:
            logger.info(f"Loading adapter: {adapter_name}")
            tokenizer = AutoTokenizer.from_pretrained(
                adapter_path, trust_remote_code=True, use_fast=False
            )
            if tokenizer.pad_token is None:
                tokenizer.pad_token = tokenizer.eos_token

            model = AutoModelForCausalLM.from_pretrained(
                self._base_model_name,
                trust_remote_code=True,
                torch_dtype=torch.bfloat16,
                device_map=None,
            )
            if self._device == "cuda":
                model = model.to("cuda")
            peft_model = PeftModel.from_pretrained(model, adapter_path)
            peft_model.to(self._device)
            peft_model.eval()

            self._model = model
            self._tokenizer = tokenizer
            self._peft_model = peft_model
            self._loaded_adapter = adapter_name

        inputs = self._tokenizer(text, return_tensors="pt", truncation=True, max_length=512).to(
            self._device
        )
        with torch.no_grad():
            outputs = self._peft_model.generate(
                **inputs,
                max_new_tokens=max_length,
                do_sample=True,
                temperature=0.7,
                pad_token_id=self._tokenizer.pad_token_id,
            )
        result = self._tokenizer.decode(outputs[0], skip_special_tokens=True)
        return result

    def unload(self):
        self._model = None
        self._tokenizer = None
        self._peft_model = None
        self._loaded_adapter = None
        import torch

        if self._device == "cuda":
            torch.cuda.empty_cache()
