package cloud.attendpro.app;

import android.content.Context;
import android.print.PrintAttributes;
import android.print.PrintDocumentAdapter;
import android.print.PrintManager;
import android.webkit.WebView;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/** Opens Android's print dialog (print or "Save as PDF") for the page on screen. */
@CapacitorPlugin(name = "AppPrint")
public class AppPrintPlugin extends Plugin {

    @PluginMethod
    public void print(PluginCall call) {
        String name = call.getString("name", "AttendPro");
        getActivity().runOnUiThread(() -> {
            WebView webView = getBridge().getWebView();
            PrintManager manager = (PrintManager) getActivity().getSystemService(Context.PRINT_SERVICE);
            PrintDocumentAdapter adapter = webView.createPrintDocumentAdapter(name);
            manager.print(name, adapter, new PrintAttributes.Builder().build());
            JSObject ret = new JSObject();
            ret.put("printed", true);
            call.resolve(ret);
        });
    }
}
