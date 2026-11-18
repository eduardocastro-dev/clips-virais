import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {title:'GTA Studio · Central de produção',description:'Estúdio pessoal de conteúdo original em português brasileiro.'};
export default function RootLayout({children}:{children:React.ReactNode}) {
  return <html lang="pt-BR"><body>{children}</body></html>;
}
