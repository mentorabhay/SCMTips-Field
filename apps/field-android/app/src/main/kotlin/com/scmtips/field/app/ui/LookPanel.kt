package com.scmtips.field.app.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
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
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.look.Fit
import com.scmtips.field.app.look.Look
import com.scmtips.field.app.look.LookPhoto
import com.scmtips.field.app.look.LookState
import com.scmtips.field.app.look.LookView
import com.scmtips.field.app.look.outlineFrame
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

/** The job screen's big Look button (the voice path is "look"; this is the hands-free fallback's big target). */
@Composable
fun LookButton(look: LookView?, a: Actions) {
    val busy = look?.busy == true
    PrimaryButton(
        if (busy) look?.state?.text ?: "Looking…" else if (look?.look != null) "Look again" else "Look · count with the camera",
        a.look, enabled = !busy, height = 64.dp,
    )
}

/**
 * The look on the phone (contract §4): the photo with every item outlined (numbered; green good, red
 * damaged) scaled from image pixels with letterboxing ([Fit]), a legend, which camera took it, the counts
 * and the proposal. Everything is SAMPLE data from the sandbox site.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun LookPanel(v: LookView, a: Actions) {
    if (v.state == LookState.IDLE) return
    CardBox(padding = androidx.compose.foundation.layout.PaddingValues(12.dp)) {
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Chip("SAMPLE", WarnBg, WarnInk)
            v.camera?.let { Chip(it.label, InfoBg, Primary) }
            v.look?.let { Chip(if (it.rulesOnly) "No model answered · count aloud" else "Read by ${it.models.joinToString { m -> m.model }.ifEmpty { "the server" }}", CardBg, Ink2, line = Line) }
        }
        v.photo?.let { photo -> OutlinedPhoto(photo, v.look) }
        if (v.busy) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.padding(top = 6.dp)) {
            CircularProgressIndicator(Modifier.size(22.dp), color = Primary, strokeWidth = 2.dp)
            Text(v.state.text, color = Muted)
        }
        if (v.labelsPending) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.padding(top = 6.dp)) {
            CircularProgressIndicator(Modifier.size(22.dp), color = Primary, strokeWidth = 2.dp)
            Text("Counted. Reading the labels…", color = Muted)
        }
        v.look?.let { LookFacts(it) }
        v.message?.let { Text(it, color = if (v.state == LookState.FAILED) Danger else Muted, fontSize = 15.sp, modifier = Modifier.padding(top = 4.dp)) }
        if (v.state == LookState.CONSENT) PrimaryButton("Agree for this site", a.agreePhotos, height = 56.dp)
        if (v.look != null) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.padding(top = 6.dp)) {
                SecondaryButton(if (v.claim != null) "Claim drafted" else if (v.claimBusy) "Making claim…" else "Make a claim",
                    a.makeClaim, Modifier.weight(1f), enabled = v.claim == null && !v.claimBusy && !v.labelsPending)
            }
        }
        v.claim?.let { c ->
            Column(Modifier.fillMaxWidth().background(WarnBg, Corner).padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("SAMPLE claim · ${c.status}", fontWeight = FontWeight.Bold, color = WarnInk)
                Text(c.text.ifBlank { com.scmtips.field.app.look.ClaimText.lines(c) }, color = Ink)
                Text("A supervisor approves it by voice before anything is sent (simulated).", fontSize = 13.sp, color = Muted)
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun LookFacts(l: Look) {
    val c = l.counts
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(top = 6.dp)) {
        c.seen?.let { Chip("Seen $it${c.expected?.let { e -> " of $e" } ?: ""}", CardBg, Ink, line = Line) }
        c.good?.let { Chip("$it good", SuccessBg, SuccessInk) }
        c.damaged?.takeIf { it > 0 }?.let { Chip("$it damaged", DangerBg, Danger) }
        if (l.packMismatches > 0) Chip("${l.packMismatches} wrong pack size", WarnBg, WarnInk)
        if (l.expiryFlagged > 0) Chip("${l.expiryFlagged} expired or near expiry", WarnBg, WarnInk)
        if (l.batches.size > 1) Chip("Mixed batches: ${l.batches.joinToString()}", WarnBg, WarnInk)
    }
    l.proposal?.let { p ->
        if (p.receive != null) Text("Say: receive ${p.receive}${p.flag?.takeIf { it > 0 }?.let { ", flag $it" } ?: ""}",
            fontWeight = FontWeight.Bold, color = Primary, fontSize = 18.sp, modifier = Modifier.padding(top = 4.dp))
        p.reasons.forEach { Text("· $it", color = Ink2, fontSize = 14.sp) }
    }
    if (l.say.isNotBlank()) Text("“${l.say}”", color = Muted, fontSize = 14.sp)
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 2.dp)) {
        Text("Visible items:", fontSize = 13.sp, color = Muted)
        Box(Modifier.size(12.dp).background(Success)); Text("good", fontSize = 13.sp, color = Ink2)
        Box(Modifier.size(12.dp).background(Danger)); Text("damaged", fontSize = 13.sp, color = Ink2)
    }
}

/** The photo drawn whole (letterboxed) with each instance's polygon or box and its number. */
@Composable
internal fun OutlinedPhoto(photo: LookPhoto, look: Look?, maxHeight: androidx.compose.ui.unit.Dp = 420.dp) {
    val image: ImageBitmap? = remember(photo) {
        BitmapFactory.decodeByteArray(photo.jpeg, 0, photo.jpeg.size)?.asImageBitmap()
    }
    val measurer = rememberTextMeasurer()
    val (fw, fh) = outlineFrame(look, photo.width, photo.height)
    val desc = look?.let { "Photo with ${it.instances.size} outlined items, ${it.instances.count { i -> i.damaged }} damaged" } ?: "Photo"
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        val density = LocalDensity.current
        val wPx = with(density) { maxWidth.toPx() }
        val hPx = Fit.heightFor(photo.width, photo.height, wPx, with(density) { maxHeight.toPx() })
        Canvas(Modifier.fillMaxWidth().height(with(density) { hPx.toDp() }).background(Color.Black, Corner).semantics { contentDescription = desc }) {
            val img = image ?: return@Canvas
            val shown = Fit.of(photo.width, photo.height, size.width, size.height) ?: return@Canvas
            drawImage(img, dstOffset = IntOffset(shown.offsetX.toInt(), shown.offsetY.toInt()),
                dstSize = IntSize(shown.drawnW.toInt(), shown.drawnH.toInt()))
            // The outlines' frame is the look's image size; the drawn photo occupies the same canvas area.
            val fit = Fit.of(fw, fh, size.width, size.height) ?: return@Canvas
            val stroke = Stroke(width = 3.dp.toPx())
            for (inst in look?.instances.orEmpty()) {
                val color = if (inst.damaged) Danger else Success
                val poly = inst.polygon
                var labelAt: Offset? = null
                if (poly != null) {
                    val path = Path()
                    poly.forEachIndexed { i, (x, y) ->
                        val (px, py) = fit.point(x, y)
                        if (i == 0) path.moveTo(px, py) else path.lineTo(px, py)
                    }
                    path.close()
                    drawPath(path, color, style = stroke)
                    val (lx, ly) = fit.point(poly.minOf { it.first }, poly.minOf { it.second })
                    labelAt = Offset(lx, ly)
                } else {
                    val b = inst.box?.let(fit::box) ?: continue
                    drawRect(color, topLeft = Offset(b.left, b.top), size = Size(b.width, b.height), style = stroke)
                    labelAt = Offset(b.left, b.top)
                }
                val text = measurer.measure("${inst.n}", TextStyle(color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.Bold))
                val tag = Size(text.size.width + 10f, text.size.height + 4f)
                val at = Offset(labelAt.x.coerceIn(0f, size.width - tag.width), labelAt.y.coerceIn(0f, size.height - tag.height))
                drawRect(color, topLeft = at, size = tag)
                drawText(text, topLeft = Offset(at.x + 5f, at.y + 2f))
            }
        }
    }
}
