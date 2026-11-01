package com.scmtips.field.app.ui.firstrun

import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.snap
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.ui.homes.ArtInk
import com.scmtips.field.app.ui.homes.GradientButton
import com.scmtips.field.app.ui.homes.LinkButton
import com.scmtips.field.app.ui.theme.Night
import com.scmtips.field.app.ui.theme.NightMuted
import com.scmtips.field.app.ui.theme.NightRaised
import com.scmtips.field.app.ui.homes.QuietButton
import kotlinx.coroutines.launch

/**
 * 1.1 Welcome (Main.dc.html): three swipeable cards (Look, Hear, Confirm), each with its looping drawing; Next,
 * the page dots (each a 48 dp tab) and a swipe move between them. "Get started" and the judges' link go on to Sign in
 * (the shell binds both to ShellAction.Welcomed). With [reduceMotion] the drawings are still and pages jump.
 */
@Composable
fun WelcomeScreen(reduceMotion: Boolean, onGetStarted: () -> Unit, onJudgeDetails: () -> Unit) {
    val cards = WelcomeCard.entries
    val pager = rememberPagerState { cards.size }
    val scope = rememberCoroutineScope()
    fun go(page: Int) = scope.launch { if (reduceMotion) pager.scrollToPage(page) else pager.animateScrollToPage(page) }
    Column(
        Modifier.fillMaxSize().background(Night).verticalScroll(rememberScrollState()).padding(start = 24.dp, end = 24.dp, top = 56.dp, bottom = 32.dp),
        verticalArrangement = Arrangement.spacedBy(24.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            BrandMark()
            Text("SCMTips Field", color = Color.White, fontSize = 17.sp, fontWeight = FontWeight.Bold)
        }
        HorizontalPager(state = pager, modifier = Modifier.fillMaxWidth()) { page ->
            val card = cards[page]
            Column(verticalArrangement = Arrangement.spacedBy(24.dp)) {
                Box(Modifier.fillMaxWidth().height(300.dp).background(NightRaised, RoundedCornerShape(24.dp)), contentAlignment = Alignment.Center) {
                    // only the page on screen animates; the others draw their still frame
                    WelcomeArt(card, reduceMotion || pager.currentPage != page)
                }
                Column(Modifier.heightIn(min = 120.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(card.title, color = Color.White, fontSize = 30.sp, lineHeight = 36.sp, fontWeight = FontWeight.Bold,
                        modifier = Modifier.semantics { heading() })
                    Text(card.body, color = NightMuted, fontSize = 17.sp, lineHeight = 25.sp)
                }
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            cards.indices.forEach { i ->
                val selected = pager.currentPage == i
                val w by animateDpAsState(if (selected) 28.dp else 8.dp, if (reduceMotion) snap() else tween(220), label = "dot")
                Box(
                    Modifier.size(width = if (selected) 44.dp else 24.dp, height = 48.dp)
                        .selectable(selected = selected, role = Role.Tab, onClick = { go(i) })
                        .semantics { contentDescription = WelcomeCard.dotLabel(i) },
                    contentAlignment = Alignment.Center,
                ) {
                    Box(Modifier.width(w).height(8.dp).background(if (selected) ArtInk.Orange else ArtInk.Dot, RoundedCornerShape(4.dp)))
                }
            }
        }
        Spacer(Modifier.height(4.dp))
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            WelcomeCard.next(pager.currentPage)?.let { n -> QuietButton("Next", { go(n) }, dark = true, height = 56.dp) }
            GradientButton("Get started", onGetStarted)
            LinkButton("For judges: SAMPLE sign-in details", onJudgeDetails, color = NightMuted, modifier = Modifier.fillMaxWidth())
        }
    }
}
