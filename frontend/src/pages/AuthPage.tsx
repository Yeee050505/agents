import React, { useState } from 'react';
import { useAuth } from '../hooks/useAuth';
import { login, register, healthCheck } from '../api/client';

interface Props {
  onEnter: () => void;
}

export default function AuthPage({ onEnter }: Props) {
  const { saveAuth, isLoggedIn } = useAuth();
  const [tab, setTab] = useState<'login' | 'register'>('login');
  const [user, setUser] = useState('');
  const [pass, setPass] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  React.useEffect(() => {
    if (isLoggedIn) {
      healthCheck().then(r => { if (r.code === 200) onEnter(); }).catch(() => {});
    }
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      if (tab === 'login') {
        const res = await login(user, pass);
        if (res.code === 200) {
          saveAuth(res.data.token, res.data.user_id);
          onEnter();
        } else {
          setError(res.msg || '登录失败');
        }
      } else {
        const res = await register(user, pass);
        if (res.code === 200) {
          saveAuth(res.data.token, res.data.user_id);
          onEnter();
        } else {
          setError(res.msg || '注册失败');
        }
      }
    } catch {
      setError('网络错误');
    }
    setLoading(false);
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900">
      <div className="w-full max-w-sm mx-4">
        <div className="text-center mb-8">
          <div className="text-5xl mb-4">🤖</div>
          <h1 className="text-2xl font-bold">多智能体平台</h1>
          <p className="text-gray-400 text-sm mt-1">Multi-Agent Platform</p>
        </div>

        <div className="bg-gray-800 rounded-2xl p-6 shadow-xl border border-gray-700">
          <div className="flex mb-6 bg-gray-900 rounded-lg p-1">
            <button
              className={`flex-1 py-2 text-sm rounded-md transition ${tab === 'login' ? 'bg-blue-600 text-white' : 'text-gray-400'}`}
              onClick={() => setTab('login')}
            >登录</button>
            <button
              className={`flex-1 py-2 text-sm rounded-md transition ${tab === 'register' ? 'bg-blue-600 text-white' : 'text-gray-400'}`}
              onClick={() => setTab('register')}
            >注册</button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <input
              className="w-full px-4 py-2.5 bg-gray-900 border border-gray-700 rounded-lg text-sm focus:outline-none focus:border-blue-500 transition"
              placeholder="用户名"
              value={user}
              onChange={e => setUser(e.target.value)}
              required
            />
            <input
              className="w-full px-4 py-2.5 bg-gray-900 border border-gray-700 rounded-lg text-sm focus:outline-none focus:border-blue-500 transition"
              type="password"
              placeholder="密码"
              value={pass}
              onChange={e => setPass(e.target.value)}
              required
            />
            {error && <p className="text-red-400 text-xs">{error}</p>}
            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg text-sm font-medium transition"
            >{loading ? '处理中...' : tab === 'login' ? '登 录' : '注 册'}</button>
          </form>

          <div className="mt-6 text-center border-t border-gray-700 pt-4">
            <p className="text-xs text-gray-500 mb-2">访客模式可直接使用</p>
            <button onClick={onEnter} className="text-blue-400 hover:text-blue-300 text-sm transition">进入体验 →</button>
          </div>
        </div>
      </div>
    </div>
  );
}
