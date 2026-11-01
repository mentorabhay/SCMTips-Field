package com.scmtips.field.app.ui.firstrun

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.glasses.GlassesAdvice
import com.scmtips.field.app.look.CameraProbe
import com.scmtips.field.app.ui.homes.ArtInk
import com.scmtips.field.app.ui.homes.GradientButton
import com.scmtips.field.app.ui.homes.LinkButton
import com.scmtips.field.app.ui.homes.Night
import com.scmtips.field.app.ui.homes.NightMuted
import com.scmtips.field.app.ui.homes.NightRaised
import com.scmtips.field.app.ui.homes.QuietButton
import com.scmtips.field.app.ui.homes.Glyph
import com.scmtips.field.app.ui.homes.GlyphKind

/**
 * 1.5 Glasses, optional (Glasses.dc.html): wake the glasses, approve SCMTips Field in Meta AI, one test photo. Each
 * step's tick comes from the real toolkit state ([advice], GlassesHelp) and the camera test's [probe], except step 1,
 * which the person confirms ("They are on"). [onSetUp] opens Meta AI or connects (the advice says which),
 * [onTestPhoto] takes the one test photo (nothing is uploaded). Skip is always there; without the toolkit it is the
 * only way on, and the phone camera does the work.
 */
@Composable
fun GlassesSetupScreen(
    advice: GlassesAdvice,
    reduceMotion: Boolean,
    onSetUp: () -> Unit,
    onTestPhoto: () -> Unit,
    onSkip: () -> Unit,
    onContinue: () -> Unit,
    probe: CameraProbe? = null,
) {
    var awake by rememberSaveable { mutableStateOf(false) }
    val m = GlassesSetupModel.from(advice, awake, probe)
    Column(
        Modifier.fillMaxSize().background(Night).verticalScroll(rememberScrollState()).padding(start = 20.dp, end = 20.dp, top = 56.dp, bottom = 28.dp),
        verticalArrangement = Arrangement.spacedBy(22.dp),
    ) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("Set up · optional", color = NightMuted, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            LinkButton("Skip", onSkip, color = NightMuted)
        }
        Box(Modifier.fillMaxWidth().height(210.dp).background(NightRaised, RoundedCornerShape(24.dp)), contentAlignment = Alignment.Center) {
            GlassesArt(reduceMotion)
        }
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Connect your glasses", color = Color.White, fontSize = 28.sp, lineHeight = 34.sp, fontWeight = FontWeight.Bold,
                modifier = Modifier.semantics { heading() })
            Text("Hands free: the glasses see, speak and listen. Without them, the phone camera does the same work.",
                color = NightMuted, fontSize = 16.sp, lineHeight = 24.sp)
        }
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            m.rows.forEachIndexed { i, r -> StepRow(i + 1, r) }
        }
        Text(listOfNotNull(m.status, m.photo).joinToString(" · "), color = NightMuted, fontSize = 14.sp, lineHeight = 20.sp,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            when (m.cta) {
                GlassesCta.AWAKE -> GradientButton(m.cta.label, { awake = true })
                GlassesCta.SET_UP, GlassesCta.CONNECT -> GradientButton(m.cta.label, onSetUp)
                GlassesCta.TEST_PHOTO -> {
                    GradientButton(if (m.busy) "Taking a photo…" else m.cta.label, onTestPhoto, enabled = !m.busy)
                    QuietButton("Continue without a test photo", onContinue, dark = true)
                }
                GlassesCta.CONTINUE -> GradientButton(m.cta.label, onContinue)
                GlassesCta.WAIT -> if (m.toolkitDown) GradientButton("Continue with the phone camera", onSkip)
                else GradientButton(m.cta.label, {}, enabled = false)
            }
        }
    }
}

@Composable
private fun StepRow(n: Int, r: GlassesStepRow) {
    val (bg, ink) = when (r.mark) {
        StepMark.DONE -> ArtInk.Live to Night
        StepMark.CURRENT -> ArtInk.Orange to Night
        StepMark.LATER -> ArtInk.Box to Color.White
    }
    val state = when (r.mark) {
        StepMark.DONE -> "done"
        StepMark.CURRENT -> "now"
        StepMark.LATER -> "to do"
    }
    Row(
        Modifier.fillMaxWidth().heightIn(min = 48.dp).background(NightRaised, RoundedCornerShape(16.dp)).padding(horizontal = 16.dp, vertical = 14.dp)
            .semantics(mergeDescendants = true) { contentDescription = "Step $n, $state: ${r.title}. ${r.sub}" },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Box(Modifier.size(30.dp).background(bg, CircleShape), contentAlignment = Alignment.Center) {
            if (r.mark == StepMark.DONE) Glyph(GlyphKind.TICK, ink, size = 18.dp, stroke = 2.6f) else Text("$n", color = ink, fontSize = 14.sp, fontWeight = FontWeight.Bold)
        }
        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(r.title, color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
            Text(r.sub, color = NightMuted, fontSize = 14.sp)
        }
    }
}
