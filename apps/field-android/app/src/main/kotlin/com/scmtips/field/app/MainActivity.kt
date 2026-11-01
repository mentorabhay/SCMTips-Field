package com.scmtips.field.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.KeyEvent
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import com.meta.wearable.dat.core.Wearables
import com.meta.wearable.dat.core.types.Permission
import com.meta.wearable.dat.core.types.PermissionStatus
import com.scmtips.field.app.glasses.DatGlasses
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

    /** Start work needs the microphone (and Bluetooth for the glasses link) before the foreground service starts. */
    private val workPermissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { granted ->
        if (granted[Manifest.permission.RECORD_AUDIO] == true || hasPermission(Manifest.permission.RECORD_AUDIO)) controller.startWork()
        else controller.toast("The microphone is needed for a work session. Allow it in Settings → Apps → SCMTips Field.")
    }

    private val locationPermission = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { granted ->
        if (granted[Manifest.permission.ACCESS_FINE_LOCATION] == true) controller.startLocation()
        else controller.toast("Location is needed to check in at the site. Allow it in Settings → Apps → SCMTips Field.")
    }

    /**
     * M5: a look photo with the phone's own camera app when the glasses give none (ACTION_IMAGE_CAPTURE into
     * this app's cache through FileProvider; the app itself holds no CAMERA permission).
     */
    private var lookFile: java.io.File? = null
    private val takeLookPhoto = registerForActivityResult(ActivityResultContracts.TakePicture()) { saved ->
        val f = lookFile
        lookFile = null
        controller.phonePhotoTaken(if (saved && f != null && f.length() > 0) f else f?.let { it.delete(); null })
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
        if (app.datInitError == null && DatGlasses.isVoiceLaunch(intent)) controller.onVoiceLaunch()
        androidPermissions.launch(
            arrayOf(Manifest.permission.BLUETOOTH_CONNECT, Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS),
        )
        lifecycleScope.launch { controller.cameraRequests.collect { scanWithCamera() } }
        lifecycleScope.launch { controller.photoRequests.collect { takePhoneLookPhoto() } }
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
            startWork = ::startWork,
            stopWork = controller::stopWork,
            pauseWork = controller::pauseWork,
            resumeWork = controller::resumeWork,
            signIn = controller::signIn,
            startReview = controller::startReview,
            stopReview = { controller.stopReview() },
            refreshDecisions = controller::refreshDecisions,
            decisionButton = controller::decisionButton,
            answerStepUp = controller::answerStepUp,
            startSandbox = controller::startSandbox,
            toggleAttentionWord = controller::toggleAttentionWord,
            look = controller::lookButton,
            makeClaim = controller::claimButton,
            agreePhotos = controller::agreeToPhotos,
            closeEvidence = controller::closeEvidence,
            startCase = controller::startCase,
            startClaims = controller::startClaimReview,
            stopClaims = { controller.stopClaimReview() },
            refreshClaims = controller::refreshClaims,
            claimButton = controller::claimCardButton,
            testCamera = ::testGlassesCamera,
            uploadProbe = { agree -> controller.uploadProbe(agree) },
            closeProbe = controller::closeProbe,
        )
        setContent {
            val ui by controller.ui.collectAsState()
            SCMTipsFieldTheme { AppRoot(ui, actions) }
        }
    }

    override fun onResume() {
        super.onResume()
        if (app.crashLog.read() == null) controller.inForeground = true
    }

    override fun onPause() {
        controller.inForeground = false
        super.onPause()
    }

    private fun hasPermission(p: String): Boolean = ContextCompat.checkSelfPermission(this, p) == PackageManager.PERMISSION_GRANTED

    private fun startWork() {
        val missing = listOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.BLUETOOTH_CONNECT, Manifest.permission.POST_NOTIFICATIONS)
            .filterNot(::hasPermission)
        if (missing.isEmpty()) controller.startWork() else workPermissions.launch(missing.toTypedArray())
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // Registration callback from the Meta AI app (scmtipsfield://...)
        if (app.datInitError == null) runCatching { Wearables.handleIntent(intent) { _ -> } }
        // "Hey Meta, start SCMTips Field" from the glasses (M4): straight to the next decision for an approver.
        if (app.datInitError == null && DatGlasses.isVoiceLaunch(intent)) controller.onVoiceLaunch()
    }

    /**
     * Handheld scanners in keyboard-wedge mode type the code and press Enter.
     * Uses the public Activity key callbacks (dispatchKeyEvent is restricted API in androidx).
     */
    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean =
        if (handleWedgeKey(event)) true else super.onKeyDown(keyCode, event)

    override fun onKeyUp(keyCode: Int, event: KeyEvent): Boolean =
        if (isWedgeKey(event)) true else super.onKeyUp(keyCode, event)

    private fun isWedgeKey(event: KeyEvent): Boolean {
        if (!controller.wantsWedge) return false
        return isTerminator(event) || event.unicodeChar != 0 // volume, back, ... are left alone
    }

    private fun isTerminator(event: KeyEvent): Boolean =
        event.keyCode == KeyEvent.KEYCODE_ENTER || event.keyCode == KeyEvent.KEYCODE_NUMPAD_ENTER ||
            event.keyCode == KeyEvent.KEYCODE_TAB

    private fun handleWedgeKey(event: KeyEvent): Boolean {
        if (!isWedgeKey(event)) return false
        if (isTerminator(event)) wedge.enter()?.let { controller.onCode(it, InputSource.SCAN) } else wedge.type(event.unicodeChar.toChar())
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

    /**
     * Me → Test glasses camera (G0-5): Bluetooth and the glasses' camera permission (granted in the Meta AI
     * app) are checked first; a missing one is asked for, and the test runs on the next tap.
     */
    private fun testGlassesCamera() {
        app.datInitError?.let { return controller.toast("Glasses toolkit: $it") }
        if (!hasPermission(Manifest.permission.BLUETOOTH_CONNECT)) {
            androidPermissions.launch(arrayOf(Manifest.permission.BLUETOOTH_CONNECT))
            return controller.toast("Allow Bluetooth for the glasses, then tap Take a test photo again.")
        }
        lifecycleScope.launch {
            Wearables.checkPermissionStatus(Permission.CAMERA)
                .onSuccess { st ->
                    if (st == PermissionStatus.Granted) controller.testGlassesCamera()
                    else { controller.toast("Allow the glasses camera in the Meta AI app, then tap again."); connectGlasses() }
                }
                .onFailure { e, _ -> controller.toast(e.description) }
        }
    }

    /** Only when a merged library manifest declares CAMERA does Android require it for ACTION_IMAGE_CAPTURE. */
    private val lookCameraPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) launchLookCamera()
        else { controller.phonePhotoTaken(null); controller.toast("The camera permission is needed for a phone photo.") }
    }

    private fun declaresPermission(p: String): Boolean = runCatching {
        @Suppress("DEPRECATION")
        packageManager.getPackageInfo(packageName, PackageManager.GET_PERMISSIONS).requestedPermissions?.contains(p) == true
    }.getOrDefault(false)

    private fun takePhoneLookPhoto() {
        if (declaresPermission(Manifest.permission.CAMERA) && !hasPermission(Manifest.permission.CAMERA)) {
            lookCameraPermission.launch(Manifest.permission.CAMERA)
        } else {
            launchLookCamera()
        }
    }

    private fun launchLookCamera() {
        val dir = java.io.File(cacheDir, "looks").apply { mkdirs() }
        val f = java.io.File(dir, "look-${System.currentTimeMillis()}.jpg")
        lookFile = f
        try {
            val uri = androidx.core.content.FileProvider.getUriForFile(this, "$packageName.looks", f)
            takeLookPhoto.launch(uri)
        } catch (e: RuntimeException) { // no camera app, or the provider is missing
            lookFile = null
            controller.phonePhotoTaken(null)
            controller.toast("The phone camera could not be opened: ${e.message ?: e.javaClass.simpleName}")
        }
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
