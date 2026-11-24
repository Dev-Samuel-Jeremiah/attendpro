import UIKit
import WebKit
import Capacitor

class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }

        window = UIWindow(windowScene: windowScene)
        // AttendPro's own screen (below), not the plain Capacitor one, so the extras load.
        window?.rootViewController = MainViewController()
        window?.makeKeyAndVisible()

        SceneDelegateProxy.shared.scene(scene, willConnectTo: session, options: connectionOptions)
    }

    func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
        SceneDelegateProxy.shared.scene(scene, openURLContexts: URLContexts)
    }

    func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
        SceneDelegateProxy.shared.scene(scene, continue: userActivity)
    }
}

/// AttendPro's one screen: attendpro.cloud in a web view, plus the few things iOS needs added.
/// (Kept in this file so it is compiled without editing the Xcode project.)
class MainViewController: CAPBridgeViewController {

    override func viewDidLoad() {
        super.viewDidLoad()
        // iPhones have no back button: swipe from the left edge to go back a page.
        webView?.allowsBackForwardNavigationGestures = true
        webView?.scrollView.bounces = false
    }

    override func capacitorDidLoad() {
        bridge?.registerPluginInstance(AppPrintPlugin())
    }
}

/// window.print() for Print buttons (wired up in static/js/app-bridge.js on the website).
@objc(AppPrintPlugin)
public class AppPrintPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "AppPrintPlugin"
    public let jsName = "AppPrint"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "print", returnType: CAPPluginReturnPromise)
    ]

    @objc func print(_ call: CAPPluginCall) {
        let name = call.getString("name") ?? "AttendPro"
        DispatchQueue.main.async {
            guard let webView = self.bridge?.webView else {
                call.reject("No page to print")
                return
            }
            let info = UIPrintInfo(dictionary: nil)
            info.outputType = .general
            info.jobName = name
            let controller = UIPrintInteractionController.shared
            controller.printInfo = info
            controller.printFormatter = webView.viewPrintFormatter()
            controller.present(animated: true) { _, completed, _ in
                call.resolve(["printed": completed])
            }
        }
    }
}
