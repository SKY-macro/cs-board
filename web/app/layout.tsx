import type {Metadata} from "next";import "./globals.css";import "./brand.css";
export const metadata:Metadata={title:"有温度出品",description:"声音可选，输入文案即可生成白板动画视频。",icons:{icon:"/brand-mark.png"}};
export default function RootLayout({children}:Readonly<{children:React.ReactNode}>){return <html lang="zh-CN"><body>{children}</body></html>}
