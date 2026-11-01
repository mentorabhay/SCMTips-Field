package com.scmtips.field.app.ui.homes

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * 5.1 Scan product home: a calm landing for "Is this unit really new?" with one big "Check a box" ([onCheckBox]; the
 * camera step itself is builder C's ScanSeal screen). The drawing shows the frame closing on a seal, never a "Code
 * read" claim. An open check offers [onOpenCheck]; a phone not linked to a site, or a site where field-api said 403,
 * says so instead of the button ([onLinkSite], when given, is the one action then).
 */
@Composable
fun ScanHome(
    model: ScanHomeModel,
    canAct: Boolean,
    reduceMotion: Boolean,
    onCheckBox: () -> Unit,
    onOpenCheck: () -> Unit,
    modifier: Modifier = Modifier,
    onLinkSite: (() -> Unit)? = null,
    contentPadding: PaddingValues = PaddingValues(16.dp),
) {
    Column(
        modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(contentPadding),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        when (model.state) {
            ScanHomeState.NOT_LINKED -> EmptyState(ScanHomeModel.NOT_LINKED, onLinkSite?.let { "Choose a site" }, { onLinkSite?.invoke() }, enabled = true) {
                SealArt(reduceMotion = true, width = 120.dp, desc = null)
            }
            ScanHomeState.NOT_ALLOWED -> EmptyState(ScanHomeModel.NOT_ALLOWED, null, {}, enabled = false) {
                SealArt(reduceMotion = true, width = 120.dp, desc = null)
            }
            ScanHomeState.READY, ScanHomeState.RUNNING -> {
                Column(
                    Modifier.fillMaxWidth().background(NightTask, RoundedCornerShape(24.dp)).padding(horizontal = 16.dp, vertical = 20.dp),
                    horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    Text(ScanHomeModel.TITLE, color = Color.White, fontSize = 22.sp, lineHeight = 28.sp, fontWeight = FontWeight.Bold,
                        textAlign = TextAlign.Center, modifier = Modifier.semantics { heading() })
                    Text(ScanHomeModel.BODY, color = NightMuted, fontSize = 15.sp, lineHeight = 22.sp, textAlign = TextAlign.Center)
                    Box(Modifier.fillMaxWidth().background(Color(0xFF1E2026), RoundedCornerShape(20.dp)).padding(vertical = 12.dp),
                        contentAlignment = Alignment.Center) {
                        SealArt(reduceMotion, width = 220.dp, desc = "A box with the maker's seal; the scan frame closes on its code")
                    }
                    Row(
                        Modifier.background(NightRaised, RoundedCornerShape(20.dp)).padding(horizontal = 14.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Glyph(GlyphKind.MIC, ArtInk.Lilac, size = 16.dp)
                        Text(ScanHomeModel.VOICE_HINT, color = Color(0xFFE5E7EB), fontSize = 14.sp)
                    }
                }
                if (model.state == ScanHomeState.RUNNING) {
                    Text("A box check is open: ${model.running.orEmpty()}", color = Ink, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
                    GradientButton("Back to the check", onOpenCheck, height = 58.dp)
                } else {
                    GradientButton("Check a box", onCheckBox, enabled = canAct, height = 58.dp)
                }
            }
        }
    }
}
