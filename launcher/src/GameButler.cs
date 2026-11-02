// 游戏日常管家 · 启动器（GameButler.exe）
//
// 做的事：以管理员身份运行；启动后台（runtime\python\pythonw.exe gb.py web）；
// 在自己的窗口里显示管家界面（WebView2，和浏览器里的网页是同一套）；
// 关闭 / 最小化窗口 = 收到右下角托盘，后台和自动调度继续跑；托盘菜单管开关和退出。
//
// 编译：launcher\build.sh（在 Linux 上用 Mono 的 mcs）。改 Python 代码不需要重新编译。
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

[assembly: AssemblyTitle("游戏日常管家")]
[assembly: AssemblyProduct("游戏日常管家")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]
[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.6.2", FrameworkDisplayName = ".NET Framework 4.6.2")]

namespace GameButler
{
    static class Program
    {
        public static string Root, DataDir, LibDir;
        public const string Url = "http://127.0.0.1:8765/";

        [STAThread]
        static void Main(string[] args)
        {
            Root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
            DataDir = Path.Combine(Root, "data");
            LibDir = Path.Combine(Root, "launcher");
            bool tray = Array.IndexOf(args, "--tray") >= 0;

            bool created;
            var mutex = new Mutex(true, "Local\\GameButler.Launcher", out created);
            var showEvt = new EventWaitHandle(false, EventResetMode.AutoReset, "Local\\GameButler.Show");
            if (!created)
            {   // 已经开着：让那个实例把窗口拿出来
                if (!tray) showEvt.Set();
                return;
            }
            try { CoreWebView2Environment.SetLoaderDllFolderPath(LibDir); } catch { }
            try { File.Delete(Path.Combine(Root, "GameButler.old.exe")); } catch { }   // 更新时改名留下的旧版本
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new ButlerApp(!tray, showEvt));
            GC.KeepAlive(mutex);
        }

        public static void OpenExternal(string target)
        {   // 通过资源管理器打开：浏览器不会继承管理员身份
            try { Process.Start(new ProcessStartInfo("explorer.exe", "\"" + target + "\"") { UseShellExecute = false }); }
            catch { }
        }

        static readonly Regex Emoji = new Regex(@"[\uD800-\uDFFF←-⇿⌀-⏿☀-➿⬀-⯿️‍]+\s*");
        public static string Plain(string s) { return Emoji.Replace(s ?? "", "").Trim(); }
    }

    // ---------- 后台接口 ----------
    static class Api
    {
        static readonly JavaScriptSerializer Js = new JavaScriptSerializer { MaxJsonLength = 64 * 1024 * 1024 };

        // 返回 (状态码, 内容)；连不上时状态码为 0
        public static int Call(string method, string path, out string body, int timeoutMs = 3000, string json = "{}")
        {
            body = null;
            try
            {
                var req = (HttpWebRequest)WebRequest.Create(Program.Url.TrimEnd('/') + path);
                req.Method = method;
                req.Proxy = null;
                req.Timeout = timeoutMs;
                req.ReadWriteTimeout = timeoutMs;
                if (method == "POST")
                {
                    var b = Encoding.UTF8.GetBytes(json);
                    req.ContentType = "application/json";
                    req.ContentLength = b.Length;
                    using (var s = req.GetRequestStream()) s.Write(b, 0, b.Length);
                }
                using (var resp = (HttpWebResponse)req.GetResponse())
                using (var r = new StreamReader(resp.GetResponseStream(), Encoding.UTF8))
                {
                    body = r.ReadToEnd();
                    return (int)resp.StatusCode;
                }
            }
            catch (WebException e)
            {
                var resp = e.Response as HttpWebResponse;
                if (resp == null) return 0;
                try { using (var r = new StreamReader(resp.GetResponseStream(), Encoding.UTF8)) body = r.ReadToEnd(); } catch { }
                return (int)resp.StatusCode;
            }
            catch { return 0; }
        }

        public static Dictionary<string, object> Get(string path, int timeoutMs = 3000)
        {
            string body;
            return Call("GET", path, out body, timeoutMs) == 200 ? Parse(body) : null;
        }

        public static bool Post(string path, string json = "{}", int timeoutMs = 5000)
        {
            string body;
            return Call("POST", path, out body, timeoutMs, json) == 200;
        }

        public static Dictionary<string, object> Parse(string s)
        {
            try { return Js.DeserializeObject(s) as Dictionary<string, object>; } catch { return null; }
        }

        public static object At(Dictionary<string, object> d, string key)
        {
            object v;
            return d != null && d.TryGetValue(key, out v) ? v : null;
        }
        public static string Str(Dictionary<string, object> d, string key) { var v = At(d, key); return v == null ? "" : Convert.ToString(v); }
        public static bool Bool(Dictionary<string, object> d, string key) { var v = At(d, key); return v is bool ? (bool)v : v != null && !(v is string && (string)v == ""); }
        public static int Int(Dictionary<string, object> d, string key) { var v = At(d, key); try { return v == null ? 0 : Convert.ToInt32(v); } catch { return 0; } }
    }

    // ---------- 自绘卡片（模块 E）：通知、调度提醒、确认框，配色字体同管家界面 ----------
    class Card : Form
    {
        public class Btn { public string Text; public string Kind; public string Value; public Btn(string t, string k, string v) { Text = t; Kind = k; Value = v; } }
        readonly bool activate;
        readonly float k;
        public string Result = "";
        public Action<string> OnChoice;
        public Action OnClickBody;
        System.Windows.Forms.Timer timer;
        Label countdown;
        DateTime? deadline;
        string countdownFmt = "";

        protected override bool ShowWithoutActivation { get { return !activate; } }
        protected override CreateParams CreateParams
        {
            get
            {
                var cp = base.CreateParams;
                cp.ExStyle |= 0x80;                       // WS_EX_TOOLWINDOW：不进任务栏 / Alt+Tab
                if (!activate) cp.ExStyle |= 0x08000000;  // WS_EX_NOACTIVATE：不抢焦点
                cp.ClassStyle |= 0x20000;                 // CS_DROPSHADOW
                return cp;
            }
        }

        public Card(string title, string body, Btn[] buttons, bool activate, bool modal)
        {
            this.activate = activate;
            using (var b = new Bitmap(1, 1)) using (var g = Graphics.FromImage(b)) k = Math.Max(1f, g.DpiX / 96f);
            FormBorderStyle = FormBorderStyle.None;
            StartPosition = FormStartPosition.Manual;
            ShowInTaskbar = false;
            TopMost = true;
            BackColor = Theme.Bg;
            Padding = new Padding(S(18), S(14), S(18), S(14));
            int w = S(modal ? 420 : 360);
            var titleL = new Label { Text = title, Font = new Font("Microsoft YaHei UI", 11f, FontStyle.Bold), ForeColor = Theme.Ink,
                                     AutoSize = false, Width = w - S(36), Location = new Point(S(18), S(14)) };
            titleL.Height = TextRenderer.MeasureText(title, titleL.Font, new Size(titleL.Width, 1000), TextFormatFlags.WordBreak).Height + S(2);
            Controls.Add(titleL);
            int y = titleL.Bottom + S(6);
            if (!string.IsNullOrEmpty(body))
            {
                var bodyL = new Label { Text = body, Font = new Font("Microsoft YaHei UI", 9.5f), ForeColor = Theme.Mute,
                                        AutoSize = false, Width = w - S(36), Location = new Point(S(18), y) };
                bodyL.Height = TextRenderer.MeasureText(body, bodyL.Font, new Size(bodyL.Width, 2000), TextFormatFlags.WordBreak).Height + S(2);
                Controls.Add(bodyL);
                y = bodyL.Bottom + S(8);
                bodyL.Click += (s, e) => ClickBody();
            }
            titleL.Click += (s, e) => ClickBody();
            countdown = new Label { Font = new Font("Microsoft YaHei UI", 8.5f), ForeColor = Theme.Faint, AutoSize = false,
                                    Width = w - S(36), Height = S(18), Location = new Point(S(18), y), Visible = false };
            Controls.Add(countdown);
            if (buttons != null && buttons.Length > 0)
            {
                y += S(4);
                int x = w - S(18);
                for (int i = buttons.Length - 1; i >= 0; i--)
                {
                    var bt = buttons[i];
                    var b = MakeButton(bt);
                    x -= b.Width;
                    b.Location = new Point(x, y);
                    x -= S(8);
                    Controls.Add(b);
                }
                y += S(34);
            }
            ClientSize = new Size(w, y + S(14));
            Region = Region.FromHrgn(CreateRoundRectRgn(0, 0, Width + 1, Height + 1, S(16), S(16)));
            Paint += (s, e) =>
            {
                e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                using (var pen = new Pen(Theme.Border))
                using (var path = Rounded(new Rectangle(0, 0, Width - 1, Height - 1), S(8)))
                    e.Graphics.DrawPath(pen, path);
            };
            Click += (s, e) => ClickBody();
            if (!modal)
            {
                var wa = Screen.PrimaryScreen.WorkingArea;
                Location = new Point(wa.Right - Width - S(16), wa.Bottom - Height - S(16));
            }
            else StartPosition = FormStartPosition.CenterScreen;
        }

        [System.Runtime.InteropServices.DllImport("gdi32.dll")]
        static extern IntPtr CreateRoundRectRgn(int l, int t, int r, int b, int w, int h);

        int S(int v) { return (int)Math.Round(v * k); }

        static System.Drawing.Drawing2D.GraphicsPath Rounded(Rectangle r, int rad)
        {
            var p = new System.Drawing.Drawing2D.GraphicsPath();
            int d = rad * 2;
            p.AddArc(r.X, r.Y, d, d, 180, 90); p.AddArc(r.Right - d, r.Y, d, d, 270, 90);
            p.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90); p.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
            p.CloseFigure();
            return p;
        }

        Control MakeButton(Btn bt)
        {
            var f = new Font("Microsoft YaHei UI", 9.5f, bt.Kind == "dark" ? FontStyle.Bold : FontStyle.Regular);
            var size = TextRenderer.MeasureText(bt.Text, f);
            var b = new Label { Text = bt.Text, Font = f, AutoSize = false, TextAlign = ContentAlignment.MiddleCenter, Cursor = Cursors.Hand,
                                Size = new Size(size.Width + S(bt.Kind == "text" ? 12 : 26), S(30)) };
            Color bg = bt.Kind == "dark" ? Theme.Ink : bt.Kind == "warn" ? Theme.Red : bt.Kind == "light" ? Color.White : Theme.Bg;
            Color fg = bt.Kind == "dark" || bt.Kind == "warn" ? Color.White : bt.Kind == "text" ? Theme.Mute : Theme.Ink;
            b.BackColor = Theme.Bg; b.ForeColor = fg;
            bool hover = false;
            b.Paint += (s, e) =>
            {
                e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                var r = new Rectangle(0, 0, b.Width - 1, b.Height - 1);
                using (var path = Rounded(r, S(8)))
                {
                    var fill = hover && bt.Kind != "dark" && bt.Kind != "warn" ? Theme.Hover : bg;
                    using (var br = new SolidBrush(fill)) e.Graphics.FillPath(br, path);
                    if (bt.Kind == "light") using (var pen = new Pen(Theme.Border)) e.Graphics.DrawPath(pen, path);
                }
                TextRenderer.DrawText(e.Graphics, bt.Text, b.Font, r, fg, TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
            };
            b.MouseEnter += (s, e) => { hover = true; b.Invalidate(); };
            b.MouseLeave += (s, e) => { hover = false; b.Invalidate(); };
            b.Click += (s, e) => Choose(bt.Value);
            return b;
        }

        void ClickBody() { if (OnClickBody != null) { var a = OnClickBody; OnClickBody = null; a(); Close(); } }

        public void Choose(string v)
        {
            Result = v;
            if (OnChoice != null) { var a = OnChoice; OnChoice = null; a(v); }
            if (Modal) DialogResult = DialogResult.OK;
            Close();
        }

        public void AutoClose(int ms)
        {
            timer = new System.Windows.Forms.Timer { Interval = ms };
            timer.Tick += (s, e) => { timer.Stop(); Close(); };
            timer.Start();
        }

        public void Countdown(DateTime until, string fmt)
        {   // fmt 里的 {0} 换成剩余「m 分 s 秒」
            deadline = until; countdownFmt = fmt; countdown.Visible = true;
            var t = new System.Windows.Forms.Timer { Interval = 1000 };
            Action upd = () =>
            {
                var left = deadline.Value - DateTime.Now;
                if (left.TotalSeconds < 0) left = TimeSpan.Zero;
                countdown.Text = string.Format(countdownFmt, (int)left.TotalMinutes + " 分 " + left.Seconds.ToString("00") + " 秒");
            };
            upd();
            t.Tick += (s, e) => upd();
            t.Start();
            FormClosed += (s, e) => t.Dispose();
        }

        // 同时只留几张通知：新的往上叠
        static readonly List<Card> stack = new List<Card>();
        public void ShowStacked()
        {
            int offset = 0;
            foreach (var c in stack) if (!c.IsDisposed) offset += c.Height + S(10);
            Top -= offset;
            stack.Add(this);
            FormClosed += (s, e) => stack.Remove(this);
            Show();
        }

        public static string Ask(string title, string body, Btn[] buttons)
        {
            using (var c = new Card(title, body, buttons, true, true))
            {
                c.ShowDialog();
                return c.Result;
            }
        }
    }

    // ---------- 托盘菜单外观：和管家界面同一套颜色（设计系统「日常管家」的 tokens） ----------
    static class Theme
    {
        public static readonly Color Bg = Color.FromArgb(0xF7, 0xF7, 0xFB);        // 界面底色 #E9EAF2 上叠白色玻璃
        public static readonly Color Ink = Color.FromArgb(0x1B, 0x1A, 0x2E);       // --ink
        public static readonly Color Mute = Color.FromArgb(0x4A, 0x49, 0x60);      // --mute
        public static readonly Color Faint = Color.FromArgb(0x9A, 0x99, 0xAB);     // 停用文字
        public static readonly Color Line = Color.FromArgb(0xE2, 0xE2, 0xEA);      // --line 叠在底色上
        public static readonly Color Border = Color.FromArgb(0xD6, 0xD6, 0xE0);
        public static readonly Color Hover = Color.FromArgb(0xE2, 0xE5, 0xF6);     // --blue-bg 叠在底色上
        public static readonly Color Track = Color.FromArgb(0xD5, 0xD5, 0xDD);     // 开关关闭时的底
        public static readonly Color Blue = Color.FromArgb(0x35, 0x50, 0xD6);
        public static readonly Color Green = Color.FromArgb(0x0F, 0x7B, 0x67);
        public static readonly Color Orange = Color.FromArgb(0xB4, 0x53, 0x0F);
        public static readonly Color Red = Color.FromArgb(0xB4, 0x23, 0x18);
    }

    class TrayMenu
    {
        [System.Runtime.InteropServices.DllImport("dwmapi.dll")]
        static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);

        public readonly ContextMenuStrip Menu;
        public readonly int IconSize;
        public readonly float K;
        public static readonly bool Win11 = Environment.OSVersion.Version.Major >= 10 && Environment.OSVersion.Version.Build >= 22000;
        readonly string iconFont;
        readonly Font font, bold;
        readonly Dictionary<string, Bitmap> glyphs = new Dictionary<string, Bitmap>();
        readonly Dictionary<int, Bitmap> dots = new Dictionary<int, Bitmap>();

        public TrayMenu()
        {
            using (var b = new Bitmap(1, 1)) using (var g = Graphics.FromImage(b)) K = Math.Max(1f, g.DpiX / 96f);
            using (var f = new Font("Segoe Fluent Icons", 10f)) iconFont = f.Name == "Segoe Fluent Icons" ? "Segoe Fluent Icons" : "Segoe MDL2 Assets";
            font = new Font("Microsoft YaHei UI", 9.5f);
            bold = new Font("Microsoft YaHei UI", 10f, FontStyle.Bold);
            IconSize = (int)Math.Round(16 * K);
            Menu = new ContextMenuStrip
            {
                Renderer = new TrayRenderer(K), Font = font, ShowImageMargin = true, ShowCheckMargin = false,
                ImageScalingSize = new Size(IconSize, IconSize), Padding = new Padding((int)(6 * K), (int)(6 * K), (int)(6 * K), (int)(6 * K)),
                BackColor = Theme.Bg, DropShadowEnabled = true
            };
            Menu.HandleCreated += (s, e) => Round(Menu.Handle);
            Menu.Opened += (s, e) => Round(Menu.Handle);
        }

        static void Round(IntPtr h)
        {   // Windows 11：系统画圆角 + 边框颜色；Windows 10 上这两个调用无效，由渲染器画直角边框
            if (!Win11) return;
            try
            {
                int round = 2; DwmSetWindowAttribute(h, 33, ref round, 4);
                int c = Theme.Border.R | (Theme.Border.G << 8) | (Theme.Border.B << 16); DwmSetWindowAttribute(h, 34, ref c, 4);
            }
            catch { }
        }

        public ToolStripMenuItem Item(string text, string glyph, EventHandler click, string tag = "")
        {
            var it = new ToolStripMenuItem(text, glyph == null ? null : Glyph(glyph), click)
            {
                Tag = tag, Font = tag == "title" ? bold : font,
                Padding = new Padding(0, (int)((tag == "title" ? 6 : 4) * K), 0, (int)((tag == "title" ? 2 : 4) * K))
            };
            if (tag == "toggle") it.ShortcutKeyDisplayString = "　　　";   // 给右边的开关留位置
            return it;
        }

        public ToolStripSeparator Sep() { return new ToolStripSeparator { Margin = new Padding(0, (int)(3 * K), 0, (int)(3 * K)) }; }

        // Segoe 图标字体里的线条图标，颜色同界面的 --mute
        public Bitmap Glyph(string ch)
        {
            Bitmap bmp;
            if (glyphs.TryGetValue(ch, out bmp)) return bmp;
            bmp = new Bitmap(IconSize, IconSize);
            using (var g = Graphics.FromImage(bmp))
            using (var f = new Font(iconFont, IconSize * 0.8f, GraphicsUnit.Pixel))
            using (var br = new SolidBrush(Theme.Mute))
            {
                g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.AntiAliasGridFit;
                var sf = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center };
                g.DrawString(ch, f, br, new RectangleF(0, 0, IconSize, IconSize + 1), sf);
            }
            glyphs[ch] = bmp;
            return bmp;
        }

        // 状态前面的小圆点：绿 = 空闲，蓝 = 运行中，橙 = 让出电脑，红 = 没有响应
        public Bitmap Dot(Color c)
        {
            Bitmap bmp;
            if (dots.TryGetValue(c.ToArgb(), out bmp)) return bmp;
            bmp = new Bitmap(IconSize, IconSize);
            using (var g = Graphics.FromImage(bmp))
            using (var br = new SolidBrush(c))
            {
                g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                float d = IconSize * 0.5f, o = (IconSize - d) / 2;
                g.FillEllipse(br, o, o, d, d);
            }
            dots[c.ToArgb()] = bmp;
            return bmp;
        }
    }

    class TrayRenderer : ToolStripRenderer
    {
        readonly float k;
        public TrayRenderer(float k) { this.k = k; }

        static System.Drawing.Drawing2D.GraphicsPath RoundRect(RectangleF r, float rad)
        {
            var p = new System.Drawing.Drawing2D.GraphicsPath();
            float d = rad * 2;
            p.AddArc(r.X, r.Y, d, d, 180, 90);
            p.AddArc(r.Right - d, r.Y, d, d, 270, 90);
            p.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
            p.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
            p.CloseFigure();
            return p;
        }

        protected override void OnRenderToolStripBackground(ToolStripRenderEventArgs e) { e.Graphics.Clear(Theme.Bg); }

        protected override void OnRenderToolStripBorder(ToolStripRenderEventArgs e)
        {
            if (TrayMenu.Win11) return;
            using (var pen = new Pen(Theme.Border))
                e.Graphics.DrawRectangle(pen, 0, 0, e.AffectedBounds.Width - 1, e.AffectedBounds.Height - 1);
        }

        protected override void OnRenderImageMargin(ToolStripRenderEventArgs e) { }
        protected override void OnRenderItemCheck(ToolStripItemImageRenderEventArgs e) { }

        protected override void OnRenderMenuItemBackground(ToolStripItemRenderEventArgs e)
        {
            var it = e.Item as ToolStripMenuItem;
            var g = e.Graphics;
            g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
            if (it.Selected && it.Enabled)
                using (var br = new SolidBrush(Theme.Hover))
                using (var path = RoundRect(new RectangleF(0, 1, it.Width - 1, it.Height - 2), 7 * k))
                    g.FillPath(br, path);
            if ((it.Tag as string) == "toggle")
            {   // 右侧开关：开 = 深色（同界面「开启」按钮），关 = 浅灰
                float h = 16 * k, w = 28 * k, x = it.Width - w - 10 * k, y = (it.Height - h) / 2;
                var on = it.Checked;
                var track = !it.Enabled ? Theme.Line : on ? Theme.Ink : Theme.Track;
                using (var br = new SolidBrush(track))
                using (var path = RoundRect(new RectangleF(x, y, w, h), h / 2))
                    g.FillPath(br, path);
                float d = h - 4 * k, kx = on ? x + w - d - 2 * k : x + 2 * k;
                using (var br = new SolidBrush(Color.White)) g.FillEllipse(br, kx, y + 2 * k, d, d);
            }
        }

        protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e)
        {
            var tag = e.Item.Tag as string;
            e.TextColor = !e.Item.Enabled ? Theme.Faint : tag == "status" ? Theme.Mute : Theme.Ink;
            base.OnRenderItemText(e);
        }

        protected override void OnRenderItemImage(ToolStripItemImageRenderEventArgs e)
        {
            if (e.Image == null) return;
            var r = e.ImageRectangle;
            r.X += (int)(4 * k);   // 和悬停底色的圆角留出距离
            if (e.Item.Enabled) e.Graphics.DrawImage(e.Image, r);
            else
                using (var ia = new System.Drawing.Imaging.ImageAttributes())
                {
                    var cm = new System.Drawing.Imaging.ColorMatrix { Matrix33 = 0.4f };
                    ia.SetColorMatrix(cm);
                    e.Graphics.DrawImage(e.Image, r, 0, 0, e.Image.Width, e.Image.Height, GraphicsUnit.Pixel, ia);
                }
        }

        protected override void OnRenderSeparator(ToolStripSeparatorRenderEventArgs e)
        {
            int y = e.Item.Height / 2;
            using (var pen = new Pen(Theme.Line))
                e.Graphics.DrawLine(pen, 8 * k, y, e.Item.Width - 8 * k, y);
        }
    }

    // ---------- 主窗口：WebView2 显示管家界面 ----------
    // 无边框（10-30）：标题栏由界面的顶栏代替。拖顶栏空白处移动窗口、双击最大化 / 还原，
    // 右上角的 — □ ✕ 发消息过来（window.chrome.webview.postMessage）。
    // 10-30 第二版：保留系统的可拉伸边框，只把标题栏那一截去掉（WM_NCCALCSIZE），所以四周拉大小、阴影、
    // 拖到屏幕边吸附、Win11 圆角都是系统自带的；上边框在页面里（顶上 5px 一条，按下发 size:12）。
    class MainForm : Form
    {
        readonly ButlerApp app;
        readonly Label loading;
        WebView2 web;
        bool maxed;

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        static extern bool ReleaseCapture();
        [System.Runtime.InteropServices.DllImport("user32.dll")]
        static extern IntPtr SendMessage(IntPtr hWnd, int msg, IntPtr wParam, IntPtr lParam);
        [System.Runtime.InteropServices.DllImport("dwmapi.dll")]
        static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);
        [System.Runtime.InteropServices.DllImport("user32.dll")]
        static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
        [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
        struct RECT { public int L, T, R, B; }
        const int WM_NCCALCSIZE = 0x83, WM_NCLBUTTONDOWN = 0xA1, HTCAPTION = 2;

        public MainForm(ButlerApp app)
        {
            this.app = app;
            Text = "游戏日常管家";
            Icon = app.AppIcon;
            FormBorderStyle = FormBorderStyle.Sizable;  // 系统边框留着拉大小；标题栏在 WndProc 里去掉
            BackColor = Color.White;
            StartPosition = FormStartPosition.CenterScreen;
            float k;
            using (var g = CreateGraphics()) k = g.DpiX / 96f;
            var wa = Screen.PrimaryScreen.WorkingArea;
            Size = new Size(Math.Min((int)(1320 * k), wa.Width - 40), Math.Min((int)(860 * k), wa.Height - 40));
            MinimumSize = new Size((int)(420 * k), (int)(480 * k));
            loading = new Label
            {
                Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter,
                Font = new Font("Microsoft YaHei UI", 12f), ForeColor = Color.FromArgb(0x4A, 0x49, 0x60),
                Text = "正在启动管家……"
            };
            Controls.Add(loading);
        }

        public void SetMessage(string text)
        {
            loading.Text = text;
            loading.Visible = true;
            loading.BringToFront();
        }

        public void Go()
        {
            if (web != null)
            {
                if (web.CoreWebView2 != null) web.CoreWebView2.Navigate(Program.Url);
                return;
            }
            web = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = BackColor };
            web.CreationProperties = new CoreWebView2CreationProperties { UserDataFolder = Path.Combine(Program.DataDir, "webview") };
            web.CoreWebView2InitializationCompleted += (s, e) =>
            {
                if (!e.IsSuccess)
                {
                    SetMessage("这台电脑缺少 Microsoft Edge WebView2 组件，已改用浏览器打开管家界面。\n" +
                               "（可在微软官网搜索「WebView2 Runtime」安装，之后界面就会显示在这个窗口里）");
                    Program.OpenExternal(Program.Url);
                    return;
                }
                var cw = web.CoreWebView2;
                cw.Settings.IsStatusBarEnabled = false;
                cw.Settings.IsZoomControlEnabled = true;
                cw.WebMessageReceived += (a, b) =>
                {
                    string msg;
                    try { msg = b.TryGetWebMessageAsString(); } catch { return; }
                    switch (msg)
                    {
                        case "drag": BeginDrag(); break;
                        case "max": ToggleMax(); break;
                        case "min": WindowState = FormWindowState.Minimized; break;
                        case "close": Close(); break;
                        case "hello": PostState(); Post("cap:pick"); break;  // 11-02：告诉页面这个启动器能自己弹选文件夹窗口
                        default:
                            if (msg.StartsWith("pick:")) { PickFolder(msg.Substring(5)); break; }
                            int hit;
                            if (msg.StartsWith("size:") && int.TryParse(msg.Substring(5), out hit)) BeginSize(hit);
                            break;
                    }
                };
                cw.NewWindowRequested += (a, b) => { b.Handled = true; Program.OpenExternal(b.Uri); };
                cw.PermissionRequested += (a, b) =>
                {
                    if (b.PermissionKind == CoreWebView2PermissionKind.Notifications) b.State = CoreWebView2PermissionState.Allow;
                };
                cw.NavigationCompleted += (a, b) => { if (b.IsSuccess) { loading.Visible = false; PostState(); } };
            };
            Controls.Add(web);
            loading.BringToFront();
            web.Source = new Uri(Program.Url);
        }

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            int round = 2;  // Windows 11：圆角（Windows 10 上这一句不起作用）
            try { DwmSetWindowAttribute(Handle, 33, ref round, 4); } catch { }
            SetWindowPos(Handle, IntPtr.Zero, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020);  // 重新算一次边框
        }

        protected override void WndProc(ref Message m)
        {
            if (m.Msg == WM_NCCALCSIZE && m.WParam != IntPtr.Zero)
            {
                // 先让系统按正常窗口算（左右下边框 = 拉大小的地方），再把上边收回到窗口顶上：没有标题栏
                var orig = (RECT)System.Runtime.InteropServices.Marshal.PtrToStructure(m.LParam, typeof(RECT));
                base.WndProc(ref m);
                var r = (RECT)System.Runtime.InteropServices.Marshal.PtrToStructure(m.LParam, typeof(RECT));
                // 最大化时窗口四边都伸出屏幕一个边框宽，上边也要留出这一截，不然顶栏会被切掉
                r.T = orig.T + (WindowState == FormWindowState.Maximized ? r.L - orig.L : 0);
                System.Runtime.InteropServices.Marshal.StructureToPtr(r, m.LParam, false);
                m.Result = IntPtr.Zero;
                return;
            }
            base.WndProc(ref m);
        }

        void BeginDrag()  // 最大化时拖动，系统会自己先还原
        {
            ReleaseCapture();
            SendMessage(Handle, WM_NCLBUTTONDOWN, (IntPtr)HTCAPTION, IntPtr.Zero);
        }

        void BeginSize(int hit)  // 页面顶上那条边：10 左 11 右 12 上 13 左上 14 右上
        {
            if (WindowState != FormWindowState.Normal || hit < 10 || hit > 17) return;
            ReleaseCapture();
            SendMessage(Handle, WM_NCLBUTTONDOWN, (IntPtr)hit, IntPtr.Zero);
        }

        void ToggleMax()
        {
            WindowState = WindowState == FormWindowState.Maximized ? FormWindowState.Normal : FormWindowState.Maximized;
        }

        void Post(string m)
        {
            try { if (web != null && web.CoreWebView2 != null) web.CoreWebView2.PostWebMessageAsString(m); }
            catch { }
        }

        // 选文件夹（11-02）：由启动器自己弹（挂在这个窗口上），不会被管家窗口挡住。消息「pick:<编号>\n<标题>」，
        // 回「pick:<编号>\n<路径>」（取消 = 空路径）。新样式窗口（能粘贴路径）打不开时退回老的文件夹树
        void PickFolder(string arg)
        {
            int nl = arg.IndexOf('\n');
            string id = nl < 0 ? arg : arg.Substring(0, nl), title = nl < 0 ? "选择文件夹" : arg.Substring(nl + 1);
            string path = "";
            try { path = FolderPicker.Pick(Handle, title); }
            catch
            {
                try
                {
                    using (var d = new FolderBrowserDialog { Description = title, ShowNewFolderButton = true })
                        if (d.ShowDialog(this) == DialogResult.OK) path = d.SelectedPath;
                }
                catch { }
            }
            Post("pick:" + id + "\n" + (path ?? ""));
        }

        void PostState()
        {
            try { if (web != null && web.CoreWebView2 != null) web.CoreWebView2.PostWebMessageAsString(maxed ? "max" : "normal"); }
            catch { }
        }

        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);
            if (WindowState == FormWindowState.Minimized) { Hide(); app.TrayHint(); return; }
            bool m = WindowState == FormWindowState.Maximized;
            if (m != maxed) { maxed = m; PostState(); }
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            if (!app.Exiting && e.CloseReason == CloseReason.UserClosing)
            {
                e.Cancel = true;
                Hide();
                app.TrayHint();
                return;
            }
            base.OnFormClosing(e);
        }
    }

    // ---------- 托盘 + 后台进程管理 ----------
    // Windows 的新样式选文件夹窗口（IFileOpenDialog + FOS_PICKFOLDERS），和资源管理器一样有地址栏、能粘贴路径
    static class FolderPicker
    {
        [System.Runtime.InteropServices.ComImport, System.Runtime.InteropServices.Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")]
        class FileOpenDialogRCW { }

        [System.Runtime.InteropServices.ComImport, System.Runtime.InteropServices.Guid("42f85136-db7e-439c-85f1-e4075d135fc8"),
         System.Runtime.InteropServices.InterfaceType(System.Runtime.InteropServices.ComInterfaceType.InterfaceIsIUnknown)]
        interface IFileDialog
        {
            [System.Runtime.InteropServices.PreserveSig] int Show(IntPtr parent);
            void SetFileTypes(uint n, IntPtr spec);
            void SetFileTypeIndex(uint i);
            void GetFileTypeIndex(out uint i);
            void Advise(IntPtr sink, out uint cookie);
            void Unadvise(uint cookie);
            void SetOptions(uint fos);
            void GetOptions(out uint fos);
            void SetDefaultFolder(IShellItem si);
            void SetFolder(IShellItem si);
            void GetFolder(out IShellItem si);
            void GetCurrentSelection(out IShellItem si);
            void SetFileName([System.Runtime.InteropServices.MarshalAs(System.Runtime.InteropServices.UnmanagedType.LPWStr)] string name);
            void GetFileName([System.Runtime.InteropServices.MarshalAs(System.Runtime.InteropServices.UnmanagedType.LPWStr)] out string name);
            void SetTitle([System.Runtime.InteropServices.MarshalAs(System.Runtime.InteropServices.UnmanagedType.LPWStr)] string title);
            void SetOkButtonLabel([System.Runtime.InteropServices.MarshalAs(System.Runtime.InteropServices.UnmanagedType.LPWStr)] string text);
            void SetFileNameLabel([System.Runtime.InteropServices.MarshalAs(System.Runtime.InteropServices.UnmanagedType.LPWStr)] string text);
            void GetResult(out IShellItem si);
        }

        [System.Runtime.InteropServices.ComImport, System.Runtime.InteropServices.Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"),
         System.Runtime.InteropServices.InterfaceType(System.Runtime.InteropServices.ComInterfaceType.InterfaceIsIUnknown)]
        interface IShellItem
        {
            void BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr ppv);
            void GetParent(out IShellItem si);
            void GetDisplayName(uint sigdn, [System.Runtime.InteropServices.MarshalAs(System.Runtime.InteropServices.UnmanagedType.LPWStr)] out string name);
        }

        const uint FOS_NOCHANGEDIR = 0x8, FOS_PICKFOLDERS = 0x20, FOS_FORCEFILESYSTEM = 0x40, SIGDN_FILESYSPATH = 0x80058000;
        const int ERROR_CANCELLED = unchecked((int)0x800704C7);

        public static string Pick(IntPtr owner, string title)
        {
            var dlg = (IFileDialog)new FileOpenDialogRCW();
            try
            {
                uint o; dlg.GetOptions(out o);
                dlg.SetOptions(o | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_NOCHANGEDIR);
                dlg.SetTitle(title);
                int hr = dlg.Show(owner);
                if (hr == ERROR_CANCELLED) return "";
                if (hr != 0) System.Runtime.InteropServices.Marshal.ThrowExceptionForHR(hr);
                IShellItem item; dlg.GetResult(out item);
                string path; item.GetDisplayName(SIGDN_FILESYSPATH, out path);
                return path ?? "";
            }
            finally { System.Runtime.InteropServices.Marshal.ReleaseComObject(dlg); }
        }
    }

    class ButlerApp : ApplicationContext
    {
        public readonly Icon AppIcon;
        public bool Exiting;
        readonly NotifyIcon tray;
        readonly SynchronizationContext ui;
        readonly ToolStripMenuItem miStatus, miStop, miSched, miYield, miAuto;
        readonly TrayMenu look;
        MainForm form;
        Process backend;
        bool ready, hinted;
        int restarts;
        DateTime restartWindow = DateTime.Now;

        // 轮询得到的状态（后台线程写，界面线程读）
        volatile bool running, paused, schedOn, schedKnown;
        volatile string statusText = "正在启动……";
        volatile bool autoStartOn, autoStartAvail = true;
        volatile int stateKind;   // 0 空闲 1 运行中 2 让出电脑 3 没有响应
        Dictionary<string, string> gameNames = new Dictionary<string, string>();
        string lastPrompt = "";

        public ButlerApp(bool showWindow, EventWaitHandle showEvt)
        {
            ui = new WindowsFormsSynchronizationContext();
            SynchronizationContext.SetSynchronizationContext(ui);
            try { AppIcon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { AppIcon = SystemIcons.Application; }

            look = new TrayMenu();
            var menu = look.Menu;
            var miTitle = look.Item("游戏日常管家", null, (s, e) => ShowWindow(), "title");
            miTitle.Image = new Icon(AppIcon, look.IconSize, look.IconSize).ToBitmap();
            miStatus = look.Item("正在启动……", null, (s, e) => ShowWindow(), "status");
            var miOpen = look.Item("打开管家", "\uE80F", (s, e) => ShowWindow());
            var miBrowser = look.Item("在浏览器中打开", "\uE774", (s, e) => Program.OpenExternal(Program.Url));
            miStop = look.Item("停止当前运行", "\uE71A", (s, e) => Bg(() => Api.Post("/api/stop")));
            miSched = look.Item("自动调度", "\uE823", (s, e) => ToggleScheduler(), "toggle");
            miYield = look.Item("让出电脑", "\uE769", (s, e) => YieldOrResume());
            miAuto = look.Item("开机自动启动", "\uE7E8", (s, e) => ToggleAutoStart(), "toggle");
            var miShortcut = look.Item("在桌面创建快捷方式", "\uE71B", (s, e) => DesktopShortcut());
            var miFolder = look.Item("打开管家文件夹", "\uE8B7", (s, e) => Program.OpenExternal(Program.Root));
            var miLogs = look.Item("查看日志文件夹", "\uE8A5", (s, e) =>
            {
                var d = Path.Combine(Program.DataDir, "logs");
                Directory.CreateDirectory(d);
                Program.OpenExternal(d);
            });
            var miExit = look.Item("退出管家", "\uE8BB", (s, e) => ExitApp());
            menu.Items.AddRange(new ToolStripItem[] {
                miTitle, miStatus, look.Sep(),
                miOpen, miBrowser, look.Sep(),
                miStop, miSched, miYield, look.Sep(),
                miAuto, miShortcut, miFolder, miLogs, look.Sep(), miExit });
            menu.Opening += (s, e) => RefreshMenu();

            tray = new NotifyIcon { Icon = AppIcon, Text = "游戏日常管家", ContextMenuStrip = menu, Visible = true };
            tray.MouseClick += (s, e) => { if (e.Button == MouseButtons.Left) ShowWindow(); };
            tray.BalloonTipClicked += (s, e) => ShowWindow();

            // 另一个 GameButler.exe 被打开时：把窗口拿出来
            var t = new Thread(() =>
            {
                while (true)
                {
                    showEvt.WaitOne();
                    ui.Post(_ => ShowWindow(), null);
                }
            }) { IsBackground = true };
            t.Start();

            if (showWindow) ShowWindow();
            new Thread(Worker) { IsBackground = true }.Start();
        }

        void Bg(Action a) { ThreadPool.QueueUserWorkItem(_ => { try { a(); } catch { } }); }

        // ---------- 窗口 ----------
        public void ShowWindow()
        {
            if (Exiting) return;
            if (form == null || form.IsDisposed)
            {
                form = new MainForm(this);
                if (ready) form.Go();
            }
            if (!form.Visible) form.Show();
            if (form.WindowState == FormWindowState.Minimized) form.WindowState = FormWindowState.Normal;
            form.Activate();
            form.BringToFront();
        }

        public void TrayHint()
        {
            if (hinted) return;
            hinted = true;
            tray.ShowBalloonTip(4000, "管家在后台继续运行", "自动调度照常进行。单击托盘图标打开界面，右键可以退出。", ToolTipIcon.Info);
        }

        void Balloon(string title, string text)
        {   // 右下角的通知卡（模块 E），点一下打开管家
            ui.Post(_ =>
            {
                try
                {
                    var c = new Card(title, text, null, false, false);
                    c.OnClickBody = () => ShowWindow();
                    c.AutoClose(7000);
                    c.ShowStacked();
                }
                catch { tray.ShowBalloonTip(6000, title, text, ToolTipIcon.Info); }
            }, null);
        }

        Card promptCard;
        void ShowPrompt(Dictionary<string, object> prompt)
        {   // 调度提醒：深色「现在开始」/ 浅色「推迟」/ 文字按钮「今天跳过」，带倒计时，置顶但不抢焦点
            ui.Post(_ =>
            {
                if (promptCard != null && !promptCard.IsDisposed) promptCard.Close();
                var choices = Api.At(prompt, "choices") as Dictionary<string, object>;
                string later = choices == null ? "推迟" : Api.Str(choices, "later");
                var tasks = Api.At(prompt, "tasks") as object[];
                int n = tasks == null ? 0 : tasks.Length;
                var c = new Card("要现在开始" + Program.Plain(Api.Str(prompt, "name")) + "吗？",
                    "管家准备运行 " + n + " 项任务。它会占用电脑前台，运行期间不能用电脑。", new[] {
                        new Card.Btn("今天跳过", "text", "skip"), new Card.Btn(later, "light", "later"), new Card.Btn("现在开始", "dark", "now") },
                    false, false);
                c.OnChoice = v => Bg(() => Api.Post("/api/scheduler/answer", "{\"choice\":\"" + v + "\"}"));
                DateTime asked;
                if (DateTime.TryParse(Api.Str(prompt, "asked_at"), out asked))
                {
                    // asked_at 是北京时间；按「问的时刻 + 5 分钟」倒计时，换算成本机时间
                    var bj = TimeZoneInfo.ConvertTimeFromUtc(DateTime.UtcNow, TimeZoneInfo.CreateCustomTimeZone("BJ", TimeSpan.FromHours(8), "BJ", "BJ"));
                    var left = asked.AddSeconds(Api.Int(prompt, "timeout_s") > 0 ? Api.Int(prompt, "timeout_s") : 300) - bj;
                    c.Countdown(DateTime.Now + left, Api.Bool(prompt, "auto_start") ? "{0} 后没回答：照样开始（这是你定的时间）" : "{0} 后没回答：等电脑空闲后自动开始");
                }
                promptCard = c;
                c.ShowStacked();
            }, null);
        }

        void HidePrompt()
        {
            ui.Post(_ => { if (promptCard != null && !promptCard.IsDisposed) promptCard.Close(); promptCard = null; }, null);
        }

        // ---------- 后台进程 ----------
        void Worker()
        {
            EnsureBackend();
            DateTime lastSettings = DateTime.MinValue;
            int failures = 0;
            DateTime lastNames = DateTime.MinValue;
            while (!Exiting)
            {
                var run = Api.Get("/api/running", 2500);
                if (run == null)
                {
                    failures++;
                    statusText = "管家后台没有响应";
                    stateKind = 3;
                    if (failures >= 3 && !Exiting)
                    {
                        if (DateTime.Now - restartWindow > TimeSpan.FromHours(1)) { restarts = 0; restartWindow = DateTime.Now; }
                        if (restarts < 3)
                        {
                            restarts++;
                            Balloon("管家后台意外退出", "正在重新启动……");
                            ready = false;
                            EnsureBackend();
                            failures = 0;
                        }
                    }
                }
                else
                {
                    failures = 0;
                    if (DateTime.Now - lastNames > TimeSpan.FromMinutes(2)) { LoadNames(); lastNames = DateTime.Now; }
                    bool nowRunning = Api.Bool(run, "running");
                    paused = Api.At(run, "paused") != null;
                    if (nowRunning)
                    {
                        var cur = Api.At(run, "current") as Dictionary<string, object>;
                        var g = Api.Str(cur, "game");
                        string name;
                        if (!gameNames.TryGetValue(g, out name)) name = g;
                        var task = Program.Plain(Api.Str(cur, "task"));
                        statusText = "正在运行：" + (name == "" ? "准备中" : name) + (task == "" ? "" : " · " + task);
                    }
                    else statusText = paused ? "已让出电脑（自动调度暂停）" : "空闲";
                    stateKind = nowRunning ? 1 : paused ? 2 : 0;
                    if (DateTime.Now - lastSettings > TimeSpan.FromSeconds(30)) { LoadSettings(); lastSettings = DateTime.Now; }
                    if (running && !nowRunning) RunFinished();
                    running = nowRunning;

                    var sch = Api.Get("/api/scheduler?launcher=1", 2500);   // launcher=1：后台就不再自己弹系统对话框
                    if (sch != null)
                    {
                        schedOn = Api.Bool(sch, "enabled");
                        schedKnown = true;
                        var prompt = Api.At(sch, "prompt") as Dictionary<string, object>;
                        var key = prompt == null ? "" : Api.Str(prompt, "game") + Api.Str(prompt, "asked_at");
                        if (key != "" && key != lastPrompt) ShowPrompt(prompt);
                        if (key == "" && lastPrompt != "") HidePrompt();
                        lastPrompt = key;
                    }
                }
                var tip = "游戏日常管家 · " + statusText;
                ui.Post(_ => { tray.Text = tip.Length > 63 ? tip.Substring(0, 62) + "…" : tip; }, null);
                Thread.Sleep(running ? 3000 : 6000);
            }
        }

        void LoadNames()
        {
            var st = Api.Get("/api/state", 8000);
            var list = Api.At(st, "games") as object[];
            if (list == null) return;
            var map = new Dictionary<string, string>();
            foreach (var o in list)
            {
                var g = o as Dictionary<string, object>;
                if (g != null) map[Api.Str(g, "id")] = Program.Plain(Api.Str(g, "name"));
            }
            gameNames = map;
        }

        void RunFinished()
        {
            var rep = Api.Get("/api/report/today", 10000);
            var sum = Api.At(rep, "summary") as Dictionary<string, object>;
            if (sum == null) { Balloon("运行结束", "打开管家查看结果。"); return; }
            int att = Api.Int(sum, "attention"), alerts = Api.Int(sum, "alerts");
            var text = "今天已完成 " + Api.Int(sum, "done") + " / " + Api.Int(sum, "total") + " 项";
            if (att > 0) text += "，" + att + " 项需要处理";
            if (alerts > 0) text += "，" + alerts + " 条提醒";
            Balloon(att > 0 ? "运行结束，有任务需要处理" : "运行结束", text + "。");
        }

        void EnsureBackend()
        {
            string body;
            int code = Api.Call("GET", "/api/app", out body, 2000);
            if (code == 200) { MarkReady(); return; }            // 已经有新版管家在跑（例如从命令行开的）
            if (code != 0) KillPortOwner();                         // 端口上是旧版管家：结束它，换成现在的代码

            var py = Path.Combine(Program.Root, "runtime\\python\\pythonw.exe");
            if (!File.Exists(py))
            {
                ui.Post(_ => MessageBox.Show("找不到 " + py + "\n请确认管家文件夹是完整的。", "游戏日常管家", MessageBoxButtons.OK, MessageBoxIcon.Error), null);
                return;
            }
            var log = Path.Combine(Program.DataDir, "logs", "butler.log");
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(log));
                backend = Process.Start(new ProcessStartInfo(py,
                    "\"" + Path.Combine(Program.Root, "gb.py") + "\" web --no-browser \"--log=" + log + "\"")
                { WorkingDirectory = Program.Root, UseShellExecute = false, CreateNoWindow = true });
            }
            catch (Exception e)
            {
                ui.Post(_ => MessageBox.Show("启动管家后台失败：" + e.Message, "游戏日常管家", MessageBoxButtons.OK, MessageBoxIcon.Error), null);
                return;
            }
            for (int i = 0; i < 120 && !Exiting; i++)
            {
                if (Api.Call("GET", "/api/app", out body, 1500) == 200) { MarkReady(); return; }
                if (backend.HasExited) break;
                Thread.Sleep(500);
            }
            ui.Post(_ =>
            {
                if (form != null && !form.IsDisposed)
                    form.SetMessage("管家后台没能启动。\n请打开托盘菜单里的「查看日志文件夹」，看 butler.log 里的错误。");
            }, null);
        }

        void MarkReady()
        {
            ready = true;
            ui.Post(_ => { if (form != null && !form.IsDisposed) form.Go(); }, null);
        }

        static void KillPortOwner()
        {
            try
            {
                var psi = new ProcessStartInfo("netstat.exe", "-ano -p TCP") { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true };
                string text;
                using (var p = Process.Start(psi)) { text = p.StandardOutput.ReadToEnd(); p.WaitForExit(5000); }
                foreach (var line in text.Split('\n'))
                {
                    var f = line.Split(new[] { ' ', '\t', '\r' }, StringSplitOptions.RemoveEmptyEntries);
                    if (f.Length >= 5 && f[1] == "127.0.0.1:8765" && (f[2] == "0.0.0.0:0" || f[3].StartsWith("LISTEN")))
                    {
                        int pid;
                        if (int.TryParse(f[f.Length - 1], out pid) && pid != Process.GetCurrentProcess().Id)
                            try { Process.GetProcessById(pid).Kill(); } catch { }
                    }
                }
                Thread.Sleep(1500);
            }
            catch { }
        }

        // ---------- 菜单 ----------
        void RefreshMenu()
        {
            miStatus.Text = statusText;
            miStatus.Image = look.Dot(stateKind == 1 ? Theme.Blue : stateKind == 2 ? Theme.Orange : stateKind == 3 ? Theme.Red : Theme.Green);
            miStop.Enabled = running;
            miSched.Enabled = schedKnown;
            miSched.Checked = schedOn;
            miYield.Text = paused ? "恢复自动调度" : "让出电脑";
            miYield.Image = look.Glyph(paused ? "\uE768" : "\uE769");
            miYield.ToolTipText = paused ? "" : "停止运行、暂停调度、关闭所有模拟器和电脑游戏";
            miAuto.Enabled = autoStartAvail;
            miAuto.Checked = autoStartOn;
        }

        void LoadSettings()
        {
            var st = Api.Get("/api/settings", 45000);
            var a = Api.At(st, "autostart") as Dictionary<string, object>;
            if (a == null) return;
            autoStartOn = Api.Bool(a, "on");
            autoStartAvail = Api.Bool(a, "available");
        }

        void ToggleScheduler()
        {
            bool on = !schedOn;
            schedOn = on;
            Bg(() => { if (!Api.Post("/api/scheduler/" + (on ? "on" : "off"))) schedOn = !on; });
        }

        void YieldOrResume()
        {
            if (paused) { Bg(() => { if (Api.Post("/api/resume")) paused = false; }); return; }
            var r = Card.Ask("让出电脑？", "会停止正在进行的运行、暂停自动调度、关闭所有模拟器和电脑游戏。之后在托盘菜单点「恢复自动调度」即可。",
                new[] { new Card.Btn("取消", "text", ""), new Card.Btn("让出电脑", "dark", "ok") });
            if (r == "ok") Bg(() => { if (Api.Post("/api/yield")) paused = true; });
        }

        void ToggleAutoStart()
        {
            bool want = !autoStartOn;
            miAuto.Enabled = false;
            Bg(() =>
            {
                bool ok = Api.Post("/api/settings/autostart", want ? "{\"on\":true}" : "{\"on\":false}", 60000);
                LoadSettings();
                ui.Post(_ =>
                {
                    miAuto.Enabled = autoStartAvail;
                    tray.ShowBalloonTip(4000, "开机自动启动",
                        !ok ? "设置失败，请到管家界面「设置」里再试一次。" : autoStartOn ? "已开启：登录 Windows 后管家会自动在托盘里启动，不弹确认窗口。" : "已关闭。",
                        ToolTipIcon.Info);
                }, null);
            });
        }

        void DesktopShortcut()
        {
            try
            {
                var desk = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
                var t = Type.GetTypeFromProgID("WScript.Shell");
                var sh = Activator.CreateInstance(t);
                var lnk = t.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, sh, new object[] { Path.Combine(desk, "游戏日常管家.lnk") });
                var lt = lnk.GetType();
                lt.InvokeMember("TargetPath", BindingFlags.SetProperty, null, lnk, new object[] { Application.ExecutablePath });
                lt.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, lnk, new object[] { Program.Root });
                lt.InvokeMember("IconLocation", BindingFlags.SetProperty, null, lnk, new object[] { Application.ExecutablePath + ",0" });
                lt.InvokeMember("Description", BindingFlags.SetProperty, null, lnk, new object[] { "游戏日常管家" });
                lt.InvokeMember("Save", BindingFlags.InvokeMethod, null, lnk, null);
                tray.ShowBalloonTip(3000, "已创建桌面快捷方式", "以后双击桌面上的「游戏日常管家」即可。", ToolTipIcon.Info);
            }
            catch (Exception e)
            {
                MessageBox.Show("创建快捷方式失败：" + e.Message, "游戏日常管家");
            }
        }

        void ExitApp()
        {
            bool stopRun = false;
            if (running)
            {
                var r = Card.Ask("退出管家？", "有任务正在运行（" + statusText + "）。可以停止这次运行再退出，也可以只退出管家、让这次运行在后台跑完。",
                    new[] { new Card.Btn("不退出", "text", ""), new Card.Btn("只退出管家", "light", "keep"), new Card.Btn("停止并退出", "warn", "stop") });
                if (r == "") return;
                stopRun = r == "stop";
            }
            Exiting = true;
            tray.Visible = false;
            if (stopRun) Api.Post("/api/stop");
            Api.Post("/api/app/quit");
            if (backend != null)
            {
                try { if (!backend.WaitForExit(8000)) backend.Kill(); } catch { }
            }
            if (form != null && !form.IsDisposed) form.Close();
            ExitThread();
        }
    }
}
