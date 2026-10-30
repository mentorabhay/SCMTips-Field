package com.scmtips.field.app

import android.Manifest
import android.content.Intent
import android.os.Bundle
import android.view.KeyEvent
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.lifecycle.lifecycleScope
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import com.meta.wearable.dat.core.Wearables
import com.meta.wearable.dat.core.types.Permission
import com.meta.wearable.dat.core.types.PermissionStatus
import com.scmtips.field.app.glasses.GlassesAdvice
import com.scmtips.field.app.jobs.InputSource
import com.scmtips.field.app.scan.WedgeBuffer
import com.scmtips.field.app.ui.Actions
import com.scmtips.field.app.ui.AppRoot
import com.scmtips.field.app.ui.CrashScreen
import com.scmtips.field.app.ui.theme.SCMTipsFieldTheme
import kotlinx.coroutines.launch

/**
 * SCMTips Field phone app (M2): connect once, Today / Scan / Me, and one job runner for every job.
 * Scanners: phone camera (Google code scanner, no camera permission), handheld wedge (key events here),
 * glasses (DAT photo + ML Kit, in FieldController).
 */
class MainActivity : ComponentActivity() {
    private val app: FieldApplication get() = application as FieldApplication
    private val controller: FieldController get() = app.controller
    private val wedge = WedgeBuffer()

    private val androidPermissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { granted ->
        // The toolkit itself is initialised in FieldApplication.onCreate; here only start watching it.
        val datError = app.datInitError
        when {
            datError != null -> controller.toast("Glasses toolkit: $datError")
            granted[Manifest.permission.BLUETOOTH_CONNECT] == true -> controller.glasses.startMonitoring()
            else -> controller.toast("Bluetooth permission is needed for the glasses")
        }
    }

    private val locationPermission = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { granted ->
        if (granted[Manifest.permission.ACCESS_FINE_LOCATION] == true) controller.startLocation()
        else controller.toast("Location is needed to check in at the site. Allow it in Settings → Apps → SCMTips Field.")
    }

    private val datPermission = registerForActivityResult(Wearables.RequestPermissionContract()) { result ->
        result.onSuccess { status -> if (status == PermissionStatus.Granted) requestNextDatPermission() }
            .onFailure { e, _ -> controller.toast(e.description) }
    }
    private val pendingDat = ArrayDeque<Permission>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // A crash on the previous run: show it (copyable) instead of starting, so it can be reported
        // without a USB cable or adb.
        app.crashLog.read()?.let { report ->
            setContent { SCMTipsFieldTheme { CrashScreen(report, onDismiss = { app.crashLog.clear(); recreate() }) } }
            return
        }
        if (app.datInitError == null) runCatching { Wearables.handleIntent(intent) { _ -> } }
        androidPermissions.launch(
            arrayOf(Manifest.permission.BLUETOOTH_CONNECT, Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS),
        )
        lifecycleScope.launch { controller.cameraRequests.collect { scanWithCamera() } }
        val actions = Actions(
            scanPairingCode = ::scanPairingQr,
            retryConnect = controller::retryConnect,
            unpair = {
                if (controller.ui.value.visitId != null) controller.toast("Check out of the site first (open the site visit).")
                else controller.unpair()
            },
            tab = controller::selectTab,
            refresh = controller::refreshTasks,
            openTask = controller::openTask,
            openStarter = controller::openStarter,
            job = controller::jobAction,
            scan = controller::requestScan,
            manualCode = { controller.onCode(it, InputSource.MANUAL) },
            manualEntryOpen = { controller.manualEntryOpen = it },
            talkStart = controller::talkStart,
            talkStop = controller::talkStop,
            startLocation = ::startLocation,
            stopLocation = controller::stopLocation,
            cycleScanner = controller::cycleScanner,
            glassesSetUp = ::glassesSetUp,
            toggleGlassesMic = controller::toggleGlassesSpeech,
            toggleAudioOnly = controller::toggleAudioOnly,
            languageInfo = { controller.toast("English for now. Hindi is coming in a later version.") },
            startPractice = controller::startPractice,
            sendFeedback = ::sendFeedback,
            dismissToast = { controller.toast(null) },
        )
        setContent {
            val ui by controller.ui.collectAsState()
            SCMTipsFieldTheme { AppRoot(ui, actions) }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // Registration callback from the Meta AI app (scmtipsfield://...)
        if (app.datInitError == null) runCatching { Wearables.handleIntent(intent) { _ -> } }
    }

    /** Handheld scanners in keyboard-wedge mode type the code and press Enter. */
    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (!controller.wantsWedge) return super.dispatchKeyEvent(event)
        val terminator = event.keyCode == KeyEvent.KEYCODE_ENTER || event.keyCode == KeyEvent.KEYCODE_NUMPAD_ENTER ||
            event.keyCode == KeyEvent.KEYCODE_TAB
        val ch = event.unicodeChar
        if (!terminator && ch == 0) return super.dispatchKeyEvent(event) // volume, back, ...
        if (event.action == KeyEvent.ACTION_DOWN) {
            if (terminator) wedge.enter()?.let { controller.onCode(it, InputSource.SCAN) } else wedge.type(ch.toChar())
        }
        return true
    }

    private fun startLocation() {
        if (!controller.startLocation()) {
            locationPermission.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
        }
    }

    private fun glassesSetUp() {
        when (controller.ui.value.glassesAdvice.action) {
            GlassesAdvice.Action.CONNECT -> connectGlasses()
            else -> controller.glassesSetUp(this)
        }
    }

    /** Glasses camera and microphone access are granted in the Meta AI app, one at a time. */
    private fun connectGlasses() {
        lifecycleScope.launch {
            pendingDat.clear()
            for (p in listOf(Permission.CAMERA, Permission.MICROPHONE)) {
                Wearables.checkPermissionStatus(p).onSuccess { s -> if (s != PermissionStatus.Granted) pendingDat += p }
            }
            if (pendingDat.isEmpty()) controller.connectGlasses() else requestNextDatPermission()
        }
    }

    private fun requestNextDatPermission() {
        val next = pendingDat.removeFirstOrNull()
        if (next == null) controller.connectGlasses() else datPermission.launch(next)
    }

    private fun scanPairingQr() {
        val options = GmsBarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build()
        GmsBarcodeScanning.getClient(this, options).startScan()
            .addOnSuccessListener { code -> code.rawValue?.let(controller::pair) }
            .addOnFailureListener { e -> controller.toast(e.message ?: "The scan did not work. Try again.") }
    }

    /** Phone camera: Google's code scanner UI (no camera permission needed by this app). */
    private fun scanWithCamera() {
        val options = GmsBarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_ALL_FORMATS).build()
        GmsBarcodeScanning.getClient(this, options).startScan()
            .addOnSuccessListener { code -> code.rawValue?.let { controller.onCode(it, InputSource.SCAN) } }
            .addOnFailureListener { e -> controller.toast(e.message ?: "The scan did not work. Try again.") }
    }

    private fun sendFeedback() {
        val text = controller.feedbackReport()
        val send = Intent(Intent.ACTION_SEND).setType("text/plain")
            .putExtra(Intent.EXTRA_SUBJECT, "SCMTips Field feedback")
            .putExtra(Intent.EXTRA_TEXT, text)
        startActivity(Intent.createChooser(send, "Send feedback"))
        controller.toast("Thanks. The report is also saved on the phone.")
    }
}
