package com.scmtips.field.app

import android.Manifest
import android.content.Intent
import android.os.Bundle
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
import com.scmtips.field.app.ui.SliceActions
import com.scmtips.field.app.ui.SliceApp
import com.scmtips.field.app.ui.theme.SCMTipsFieldTheme
import kotlinx.coroutines.launch

/**
 * M1 field-test slice (A-01): pair with the PC, connect Ray-Ban Meta through the Meta AI app, receive
 * an inbound delivery by glasses photo + voice, hear the ERP result.
 */
class MainActivity : ComponentActivity() {
    private val controller: SliceController get() = (application as FieldApplication).controller

    private val androidPermissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { granted ->
        if (granted[Manifest.permission.BLUETOOTH_CONNECT] == true) {
            Wearables.initialize(this)
                .onSuccess { controller.glasses.startMonitoring() }
                .onFailure { e, _ -> showToast("Glasses toolkit: ${e.description}") }
        }
    }

    private val datPermission = registerForActivityResult(Wearables.RequestPermissionContract()) { result ->
        result.onSuccess { status -> if (status == PermissionStatus.Granted) requestNextDatPermission() }
            .onFailure { e, _ -> showToast(e.description) }
    }
    private val pendingDat = ArrayDeque<Permission>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Wearables.handleIntent(intent) { _ -> }
        androidPermissions.launch(
            arrayOf(Manifest.permission.BLUETOOTH_CONNECT, Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS),
        )
        val actions = SliceActions(
            scanPairingQr = ::scanPairingQr,
            unpair = controller::unpair,
            registerGlasses = { controller.registerGlasses(this) },
            connectGlasses = ::connectGlasses,
            setGlassesSpeech = controller::setGlassesSpeech,
            refresh = controller::refreshTasks,
            open = controller::open,
            close = controller::close,
            capture = controller::capture,
            next = controller::next,
            talkStart = controller::talkStart,
            talkStop = controller::talkStop,
        )
        setContent {
            val ui by controller.ui.collectAsState()
            SCMTipsFieldTheme { SliceApp(ui, actions) }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // Registration callback from the Meta AI app (scmtipsfield://...)
        Wearables.handleIntent(intent) { _ -> }
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
            .addOnFailureListener { e -> showToast(e.message ?: "scan failed") }
    }

    private fun showToast(text: String) {
        android.widget.Toast.makeText(this, text, android.widget.Toast.LENGTH_LONG).show()
    }
}
