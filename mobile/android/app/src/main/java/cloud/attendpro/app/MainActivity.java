package cloud.attendpro.app;

import android.app.DownloadManager;
import android.content.Context;
import android.graphics.Color;
import android.os.Build;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.webkit.CookieManager;
import android.webkit.URLUtil;
import android.webkit.WebView;
import android.widget.Toast;

import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsControllerCompat;

import com.getcapacitor.BridgeActivity;

/**
 * AttendPro's one screen: attendpro.cloud in a native web view, plus what Android needs added.
 * Pages, features and fixes all come from the website, so they never need an app update.
 */
public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(AppPrintPlugin.class);       // window.print() for Print buttons (static/js/app-bridge.js)
        super.onCreate(savedInstanceState);
        enableDownloads(getBridge().getWebView());
        brandSystemBars();
    }

    /**
     * Android 15+ draws apps edge to edge and no longer lets apps colour the status bar. The app keeps
     * the page clear of the bars, so what shows behind them is the window background: make it navy,
     * like AttendPro's headers, with light icons so the clock and battery stay readable.
     */
    private void brandSystemBars() {
        if (Build.VERSION.SDK_INT < 35) return;
        getWindow().getDecorView().setBackgroundColor(Color.parseColor("#0d1530"));
        WindowInsetsControllerCompat bars = WindowCompat.getInsetsController(getWindow(), getWindow().getDecorView());
        bars.setAppearanceLightStatusBars(false);
        bars.setAppearanceLightNavigationBars(false);
    }

    /** Reports, payslips and backups go to the phone's Downloads folder, still signed in. */
    private void enableDownloads(WebView webView) {
        webView.setDownloadListener((url, userAgent, contentDisposition, mimeType, contentLength) -> {
            try {
                String name = URLUtil.guessFileName(url, contentDisposition, mimeType);
                DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
                String cookies = CookieManager.getInstance().getCookie(url);
                if (cookies != null) request.addRequestHeader("Cookie", cookies);
                request.addRequestHeader("User-Agent", userAgent);
                request.setMimeType(mimeType);
                request.setTitle(name);
                request.setDescription("Downloading from AttendPro");
                request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
                DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
                dm.enqueue(request);
                Toast.makeText(this, "Downloading " + name, Toast.LENGTH_SHORT).show();
            } catch (Exception e) {
                Toast.makeText(this, "Couldn't download the file", Toast.LENGTH_LONG).show();
            }
        });
    }
}
