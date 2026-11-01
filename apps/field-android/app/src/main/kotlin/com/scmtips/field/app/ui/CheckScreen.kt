package com.scmtips.field.app.ui

import android.graphics.BitmapFactory
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.check.AuthenticityCheck
import com.scmtips.field.app.check.CheckAction
import com.scmtips.field.app.check.CheckState
import com.scmtips.field.app.check.CheckText
import com.scmtips.field.app.check.CheckView
import com.scmtips.field.app.check.VerdictTone
import com.scmtips.field.app.look.ClaimText
import com.scmtips.field.app.look.Fit
import com.scmtips.field.app.look.LookFlow
import com.scmtips.field.app.look.LookPhoto
import com.scmtips.field.app.ui.theme.CardBg
import com.scmtips.field.app.ui.theme.Danger
import com.scmtips.field.app.ui.theme.DangerBg
import com.scmtips.field.app.ui.theme.InfoBg
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.theme.Ink2
import com.scmtips.field.app.ui.theme.Line
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.app.ui.theme.Primary
import com.scmtips.field.app.ui.theme.Success
import com.scmtips.field.app.ui.theme.SuccessBg
import com.scmtips.field.app.ui.theme.SuccessInk
import com.scmtips.field.app.ui.theme.WarnBg
import com.scmtips.field.app.ui.theme.WarnInk
import com.scmtips.field.app.ui.theme.WarnText

/** Today's "Check a delivered box" card (M5-T05): no task is needed; any Field role the server allows. */
@Composable
fun CheckBoxCard(workActive: Boolean, a: Actions) {
    CardBox {
        Text("Is this unit really new? (SAMPLE)", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = Muted)
        Text("Check a delivered box", fontWeight = FontWeight.Bold, color = Ink, fontSize = 18.sp)
        Text(
            if (workActive) "Say “check this box”, then show the seal's QR code to the glasses."
            else "Show the seal's QR code to the glasses or the phone. The maker's records answer; the maker here is a simulator.",
            color = Ink2, fontSize = 14.sp,
        )
        PrimaryButton("Check a box", { a.check(CheckAction.START) }, Modifier.padding(top = 6.dp), height = 56.dp)
    }
}

/**
 * The box check card (contract §7): the verdict big and colour-coded (green new, amber not new, grey cannot
 * verify, red likely counterfeit, a "seal tampered" chip), the signals (signature, history, first check, seal),
 * the photo with the seal box, and the buttons for what can also be said: make a claim, evidence page, check
 * again, done.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun CheckScreen(v: CheckView, workActive: Boolean, a: Actions) {
    BackHandler { a.check(CheckAction.DONE) }
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Is this unit really new?", fontSize = 26.sp, fontWeight = FontWeight.Bold, color = Ink, lineHeight = 30.sp)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Chip("SAMPLE · the maker is a simulator", WarnBg, WarnInk)
            v.camera?.let { Chip(it.label, InfoBg, Primary) }
            v.codeSource?.let { Chip(it.label, CardBg, Ink2, line = Line) }
            if (v.photoSent == false && v.check != null) Chip("Code only · no photo sent", CardBg, Ink2, line = Line)
        }
        if (v.busy) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            CircularProgressIndicator(Modifier.size(22.dp), color = Primary, strokeWidth = 2.dp)
            Text(v.state.text, color = Muted, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        }
        v.check?.let { c -> VerdictBlock(c, v.visualPending) }
        v.message?.let {
            Text(it, color = if (v.state == CheckState.FAILED || v.state == CheckState.NO_CODE) Danger else Ink2, fontSize = 15.sp,
                modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        }
        when (v.state) {
            CheckState.NO_CODE -> {
                PrimaryButton("Scan the code with the phone", { a.check(CheckAction.PHONE_SCAN) }, height = 60.dp)
                SecondaryButton("Take the photo again", { a.check(CheckAction.START) })
            }
            CheckState.CONSENT -> {
                Text(LookFlow.CONSENT_TEXT, color = Ink2, fontSize = 14.sp)
                PrimaryButton("Agree for this site", { a.check(CheckAction.AGREE) }, height = 56.dp)
                SecondaryButton("Check by code only", { a.check(CheckAction.CODE_ONLY) })
            }
            CheckState.FAILED -> if (v.canRetry) PrimaryButton("Try again", { a.check(CheckAction.RETRY) }, height = 56.dp)
            else -> Unit
        }
        v.check?.let { c -> Signals(c, v.visualPending) }
        v.photo?.let { SealPhoto(it, v.check) }
        v.claim?.let { cl ->
            Column(Modifier.fillMaxWidth().background(WarnBg, Corner).padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("SAMPLE claim · ${cl.status}", fontWeight = FontWeight.Bold, color = WarnInk)
                Text(ClaimText.body(cl), color = Ink)
                Text("A supervisor approves it by voice before anything is sent (simulated).", fontSize = 13.sp, color = Muted)
            }
        }
        if (v.check != null) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                PrimaryButton(
                    when {
                        v.claim != null -> "Claim drafted"
                        v.claimBusy -> "Making claim…"
                        v.visualPending -> "Checking the seal…"
                        v.claimable -> "Make a claim"
                        else -> "Nothing to claim"
                    },
                    { a.check(CheckAction.CLAIM) }, Modifier.weight(1f), enabled = v.claimable && v.claim == null && !v.claimBusy, height = 56.dp,
                )
                SecondaryButton("Evidence page", { a.check(CheckAction.EVIDENCE) }, Modifier.weight(1f))
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            SecondaryButton("Check again", { a.check(CheckAction.AGAIN) }, Modifier.weight(1f), enabled = !v.busy)
            SecondaryButton("Done", { a.check(CheckAction.DONE) }, Modifier.weight(1f))
        }
        Text(
            if (workActive) "You can say: make a claim, show evidence, check again, done."
            else "Hold to talk on a job screen, or start work to use your voice.",
            color = Muted, fontSize = 13.sp,
        )
    }
}

@Composable
private fun VerdictBlock(c: AuthenticityCheck, visualPending: Boolean) {
    val (bg, fg) = when (c.verdict.tone) {
        VerdictTone.GREEN -> SuccessBg to SuccessInk
        VerdictTone.AMBER -> WarnBg to WarnInk
        VerdictTone.GREY -> Color(0xFFEDEEF0) to Ink
        VerdictTone.RED -> DangerBg to Danger
    }
    val dot = when (c.verdict.tone) {
        VerdictTone.GREEN -> Success
        VerdictTone.AMBER -> WarnText
        VerdictTone.GREY -> Muted
        VerdictTone.RED -> Danger
    }
    Column(Modifier.fillMaxWidth().background(bg, Corner).padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(Modifier.size(16.dp).background(dot, CircleShape))
            Text(c.verdict.headline, color = fg, fontSize = 26.sp, fontWeight = FontWeight.Bold, lineHeight = 30.sp,
                modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (c.tamper == true) Chip("Seal tampered", DangerBg, Danger, dot = Danger)
            if (visualPending) Chip("Checking the seal…", CardBg, Ink2, line = Line)
        }
        if (c.say.isNotBlank()) Text("“${c.say}”", color = Ink2, fontSize = 15.sp)
    }
}

@Composable
private fun Signals(c: AuthenticityCheck, visualPending: Boolean) {
    CardBox {
        Text("What was checked", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = Muted)
        Fact("Signature", CheckText.signature(c.code))
        CheckText.unit(c.code)?.let { Fact("Unit", it) }
        Fact("First check", CheckText.firstCheck(c.firstCheck))
        Fact("Seal", if (visualPending) "Checking the seal…" else CheckText.visual(c.visual, c.tamper))
        Text("History", fontWeight = FontWeight.Bold, color = Ink, modifier = Modifier.padding(top = 6.dp))
        val events = c.registry?.events.orEmpty()
        CheckText.registry(c.registry)?.let { Text(it, color = Ink2, fontSize = 15.sp) }
        events.zip(CheckText.timeline(c.registry)).forEach { (e, line) ->
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Box(Modifier.size(10.dp).background(if (CheckText.notNewEvent(e.type)) WarnText else Primary, CircleShape))
                Text(line, color = if (CheckText.notNewEvent(e.type)) WarnInk else Ink, fontSize = 15.sp,
                    fontWeight = if (CheckText.notNewEvent(e.type)) FontWeight.Bold else FontWeight.Normal)
            }
        }
        if (events.isEmpty() && CheckText.registry(c.registry) == null) Text("No history sent.", color = Muted, fontSize = 15.sp)
    }
}

@Composable
private fun Fact(label: String, value: String) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("$label:", fontWeight = FontWeight.Bold, color = Ink, fontSize = 15.sp)
        Text(value, color = Ink2, fontSize = 15.sp)
    }
}

/** The seal photo drawn whole (letterboxed, [Fit]) with the seal box the visual check outlined, in image pixels. */
@Composable
private fun SealPhoto(photo: LookPhoto, c: AuthenticityCheck?) {
    val image: ImageBitmap? = remember(photo) { BitmapFactory.decodeByteArray(photo.jpeg, 0, photo.jpeg.size)?.asImageBitmap() }
    val visual = c?.visual
    val fw = visual?.imageWidth ?: photo.width
    val fh = visual?.imageHeight ?: photo.height
    val tampered = c?.tamper == true
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        val density = LocalDensity.current
        val wPx = with(density) { maxWidth.toPx() }
        val hPx = Fit.heightFor(photo.width, photo.height, wPx, with(density) { 360.dp.toPx() })
        val desc = if (visual?.box != null) "Seal photo with the seal outlined" else "Seal photo"
        Canvas(Modifier.fillMaxWidth().height(with(density) { hPx.toDp() }).background(Color.Black, Corner).semantics { contentDescription = desc }) {
            val img = image ?: return@Canvas
            val shown = Fit.of(photo.width, photo.height, size.width, size.height) ?: return@Canvas
            drawImage(img, dstOffset = IntOffset(shown.offsetX.toInt(), shown.offsetY.toInt()),
                dstSize = IntSize(shown.drawnW.toInt(), shown.drawnH.toInt()))
            val fit = Fit.of(fw, fh, size.width, size.height) ?: return@Canvas
            val b = visual?.box?.let(fit::box) ?: return@Canvas
            drawRect(if (tampered) Danger else Success, topLeft = Offset(b.left, b.top), size = Size(b.width, b.height),
                style = Stroke(width = 3.dp.toPx()))
        }
    }
}
