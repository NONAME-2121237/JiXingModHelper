using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace JiXingModHelperHost;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        var url = ReadArgument(args, "--url");
        if (string.IsNullOrWhiteSpace(url))
        {
            MessageBox.Show("缺少本地页面地址。", "吉星派对 Mod 助手", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        using var window = new MainWindow(
            url,
            ReadArgument(args, "--profile"),
            ReadArgument(args, "--icon")
        );
        Application.Run(window);
    }

    private static string ReadArgument(IReadOnlyList<string> args, string name)
    {
        for (var index = 0; index + 1 < args.Count; index++)
        {
            if (string.Equals(args[index], name, StringComparison.OrdinalIgnoreCase))
            {
                return args[index + 1];
            }
        }
        return string.Empty;
    }
}

internal sealed class MainWindow : Form
{
    private readonly WebView2 _webView = new() { Dock = DockStyle.Fill };
    private readonly string _url;
    private readonly string _profilePath;

    public MainWindow(string url, string profilePath, string iconPath)
    {
        _url = url;
        _profilePath = profilePath;
        Text = "吉星派对 Mod 助手";
        // 默认接近用户截图外框 ~1866×1182（含标题栏），客户区略大便于浏览
        ClientSize = new Size(1840, 1120);
        MinimumSize = new Size(1280, 800);
        StartPosition = FormStartPosition.CenterScreen;
        Controls.Add(_webView);

        if (File.Exists(iconPath))
        {
            try
            {
                Icon = new Icon(iconPath);
            }
            catch (ArgumentException)
            {
                // 图标文件无效时仍可正常显示页面。
            }
        }

        Shown += async (_, _) => await InitializeWebViewAsync();
    }

    private async Task InitializeWebViewAsync()
    {
        try
        {
            if (!string.IsNullOrWhiteSpace(_profilePath))
            {
                Directory.CreateDirectory(_profilePath);
            }
            var options = new CoreWebView2EnvironmentOptions
            {
                // 本应用只连本地 127.0.0.1，禁用代理避免系统代理/VPN 把本地请求也拦掉
                AdditionalBrowserArguments = "--no-proxy-server"
            };
            var environment = await CoreWebView2Environment.CreateAsync(
                browserExecutableFolder: null,
                userDataFolder: string.IsNullOrWhiteSpace(_profilePath) ? null : _profilePath,
                options: options
            );
            await _webView.EnsureCoreWebView2Async(environment);
            _webView.Source = new Uri(_url);
        }
        catch (Exception exception)
        {
            MessageBox.Show(
                $"无法初始化 HTML 界面。\n\n{exception.Message}",
                "吉星派对 Mod 助手",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
            Close();
        }
    }
}
