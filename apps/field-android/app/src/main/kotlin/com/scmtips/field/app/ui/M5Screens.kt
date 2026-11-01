package com.scmtips.field.app.ui

import android.graphics.BitmapFactory
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import com.scmtips.field.app.home.CaseStart
import com.scmtips.field.app.look.CameraProbe
import com.scmtips.field.app.look.ClaimsText
import com.scmtips.field.app.look.ClaimsView
import com.scmtips.field.app.ui.theme.CardBg
import com.scmtips.field.app.ui.theme.InfoBg
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.theme.Ink2
import com.scmtips.field.app.ui.theme.Line
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.app.ui.theme.Primary
import com.scmtips.field.app.ui.theme.SuccessBg
import com.scmtips.field.app.ui.theme.SuccessInk
import com.scmtips.field.app.ui.theme.WarnBg
import com.scmtips.field.app.ui.theme.WarnInk

/** Today on a sandbox site: the two M5 cases, each with its short "How to test" card (contract §1). */
@Composable
fun CaseStarterCards(cases: List<CaseStart>, workActive: Boolean, a: Actions) {
    if (cases.isEmpty()) return
    var open by remember { mutableStateOf<CaseStart?>(null) }
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Test cases (SAMPLE)", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = Muted)
        cases.forEach { c ->
            Column(Modifier.fillMaxWidth().background(WarnBg, Corner).border(1.dp, Line, Corner).padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(c.label, fontWeight = FontWeight.Bold, color = Ink, fontSize = 18.sp)
                Text(c.sub + if (workActive) " · or say “${c.label.lowercase()}”" else "", fontSize = 14.sp, color = Muted)
                PrimaryButton("Start: ${c.label}", { a.startCase(c) }, height = 60.dp)
                Text(if (open == c) "Hide how to test" else "How to test", color = Primary, fontWeight = FontWeight.Bold,
                    modifier = Modifier.heightIn(min = 48.dp).clickable(role = Role.Button) { open = if (open == c) null else c }.padding(vertical = 12.dp))
                if (open == c) {
                    Column(Modifier.fillMaxWidth().background(CardBg, Corner).padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(c.howTo.title, fontWeight = FontWeight.Bold, color = Ink)
                        c.howTo.steps.forEachIndexed { i, s -> Text("${i + 1}. $s", color = Ink2, fontSize = 15.sp) }
                        Text("Nothing here is real stock: the site is a sandbox and every item is SAMPLE.", color = Muted, fontSize = 13.sp)
                    }
                }
            }
        }
    }
}

/** Today's Claims card for supervisors (shown only when the server lets this person list draft claims). */
@Composable
fun ClaimsCard(c: ClaimsView, workActive: Boolean, a: Actions) {
    val n = c.waiting ?: return
    CardBox {
        Text("Supplier claims (SAMPLE)", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = Muted)
        Text(ClaimsText.chip(n), fontWeight = FontWeight.Bold, color = Ink, fontSize = 17.sp)
        Text(
            if (workActive) "Say “claims” to hear the first draft, then “approve” or “reject”, and “confirm”."
            else "Each draft is read aloud. Answer by voice: hold the talk button, or start work and just speak.",
            color = Ink2, fontSize = 14.sp,
        )
        c.last?.let { Text("Last: $it", color = Muted, fontSize = 13.sp) }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            PrimaryButton("Review claims", a.startClaims, Modifier.weight(1f), enabled = n > 0, height = 52.dp)
            SecondaryButton("Check again", a.refreshClaims, Modifier.weight(1f))
        }
    }
}

/** The running claims review: the card and its big buttons (shortcuts for the spoken words). */
@Composable
fun ClaimReviewScreen(c: ClaimsView, a: Actions) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text("Claims", fontSize = 28.sp, fontWeight = FontWeight.Bold, color = Ink)
        Chip("SAMPLE · sending to the supplier is simulated", WarnBg, WarnInk)
        Text(c.state, color = if (c.listening) SuccessInk else Ink2, fontSize = 15.sp,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }
                .then(if (c.listening) Modifier.background(SuccessBg, Corner).padding(horizontal = 10.dp, vertical = 6.dp) else Modifier))
        c.card?.let { card ->
            CardBox {
                Text(card.title, fontWeight = FontWeight.Bold, color = Ink, fontSize = 18.sp)
                Text(card.body, color = Ink2, fontSize = 16.sp)
                card.buttons.forEach { b ->
                    if (b.primary) PrimaryButton(b.label, { a.claimButton(b.id) }, Modifier.fillMaxWidth(), height = 60.dp)
                    else SecondaryButton(b.label, { a.claimButton(b.id) }, Modifier.fillMaxWidth())
                }
            }
        }
        HoldToTalkBig(a)
        SecondaryButton("Stop", a.stopClaims, Modifier.fillMaxWidth(), ink = WarnInk)
    }
}

@Composable
private fun HoldToTalkBig(a: Actions) {
    var held by remember { mutableStateOf(false) }
    Box(
        Modifier.fillMaxWidth().heightIn(min = 72.dp).background(if (held) Primary else InfoBg, Corner)
            .pointerInput(Unit) {
                detectTapGestures(onPress = {
                    held = true
                    a.talkStart()
                    tryAwaitRelease()
                    held = false
                    a.talkStop()
                })
            },
        contentAlignment = Alignment.Center,
    ) {
        Text(if (held) "Listening… let go when done" else "Hold to talk (without a work session)", color = if (held) Color.White else Primary,
            fontWeight = FontWeight.Bold, fontSize = 17.sp)
    }
}

/**
 * The evidence page after a posting (contract §3): field-api's signed, self-contained HTML page in a
 * WebView (platform android.webkit, no new library). JavaScript and file access stay off: the page is
 * plain HTML and SVG.
 */
@Composable
fun EvidenceScreen(url: String, a: Actions) {
    BackHandler { a.closeEvidence() }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Column(Modifier.weight(1f)) {
                Text("Evidence page", fontWeight = FontWeight.Bold, color = Ink, fontSize = 20.sp)
                Text("SAMPLE · photo, outlines, checks, models and your confirm", color = Muted, fontSize = 13.sp)
            }
            SmallButton("Close", a.closeEvidence)
        }
        AndroidView(
            factory = { ctx ->
                WebView(ctx).apply {
                    settings.javaScriptEnabled = false
                    settings.allowFileAccess = false
                    settings.allowContentAccess = false
                    webViewClient = WebViewClient()
                    loadUrl(url)
                }
            },
            update = { w -> if (w.url != url) w.loadUrl(url) },
            modifier = Modifier.fillMaxWidth().weight(1f),
        )
    }
}

/** Me → Test glasses camera (Gate 0 probe G0-5): size and delay of one toolkit photo; Upload only on a tap. */
@Composable
fun CameraTestCard(p: CameraProbe?, a: Actions) {
    CardBox {
        Text("Test glasses camera", fontWeight = FontWeight.Bold, color = Ink)
        Text("Takes one photo through the Meta toolkit and shows its size and how long it took. Nothing is sent unless you tap Upload.",
            color = Muted, fontSize = 14.sp)
        if (p == null) {
            PrimaryButton("Take a test photo", a.testCamera, height = 56.dp)
            return@CardBox
        }
        p.summary?.let { Text(it, fontWeight = FontWeight.Bold, color = Ink, fontSize = 17.sp) }
        p.preview?.let { photo ->
            val img = remember(photo) { BitmapFactory.decodeByteArray(photo.jpeg, 0, photo.jpeg.size)?.asImageBitmap() }
            img?.let {
                Image(it, contentDescription = "Test photo from the glasses (faces blurred)", contentScale = ContentScale.FillWidth,
                    modifier = Modifier.fillMaxWidth().heightIn(max = 320.dp).background(Color.Black, Corner))
            }
            Text("Shown and uploaded at ${photo.width} × ${photo.height} px, ${photo.jpeg.size / 1024} KB, faces blurred: ${photo.facesBlurred}.",
                color = Muted, fontSize = 13.sp)
        }
        p.message?.let { Text(it, color = Ink2, fontSize = 14.sp) }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            SecondaryButton(if (p.busy) "Working…" else "Again", a.testCamera, Modifier.weight(1f), enabled = !p.busy)
            when {
                p.needsConsent -> PrimaryButton("Agree and upload", { a.uploadProbe(true) }, Modifier.weight(1f), enabled = !p.busy, height = 52.dp)
                p.preview != null && p.uploadedCaptureId == null -> PrimaryButton("Upload", { a.uploadProbe(false) }, Modifier.weight(1f), enabled = !p.busy, height = 52.dp)
                else -> SecondaryButton("Close", a.closeProbe, Modifier.weight(1f))
            }
        }
    }
}
