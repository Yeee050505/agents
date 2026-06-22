import { useState } from 'react';
import { useAuth } from './hooks/useAuth';
import AuthPage from './pages/AuthPage';
import ChatPage from './pages/ChatPage';

export default function App() {
  const [inChat, setInChat] = useState(false);
  const { isLoggedIn } = useAuth();

  if (inChat || isLoggedIn) {
    return <ChatPage onLogout={() => setInChat(false)} />;
  }

  return <AuthPage onEnter={() => setInChat(true)} />;
}
