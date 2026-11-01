package com.scmtips.field.app.ui.firstrun

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.shell.Home
import com.scmtips.field.app.shell.HomeChoice
import com.scmtips.field.app.signin.SiteRef
import com.scmtips.field.app.ui.homes.AccentInk
import com.scmtips.field.app.ui.homes.AccentSelected
import com.scmtips.field.app.ui.homes.AccentTint
import com.scmtips.field.app.ui.homes.Border
import com.scmtips.field.app.ui.homes.BrandStart
import com.scmtips.field.app.ui.homes.CardShape
import com.scmtips.field.app.ui.homes.Glyph
import com.scmtips.field.app.ui.homes.GlyphKind
import com.scmtips.field.app.ui.homes.GradientButton
import com.scmtips.field.app.ui.homes.Ground
import com.scmtips.field.app.ui.homes.Ink
import com.scmtips.field.app.ui.homes.Muted
import com.scmtips.field.app.ui.homes.QuietTint
import com.scmtips.field.app.ui.homes.SandboxInk
import com.scmtips.field.app.ui.homes.Surface
import com.scmtips.field.app.ui.homes.Tag
import com.scmtips.field.app.ui.homes.WarnBg
import androidx.compose.ui.graphics.Color

/**
 * 1.6 Your site (Site.dc.html): "Where are you working?" from field-api's [sites] (a sandbox site is marked), then
 * "What are you doing now?" with every home of [homes]; a view-only home can be picked (reviewers open every home)
 * and says so. A PC pairing has no list: its [pairedSiteName] is shown as the one site. Continue needs a site, unless
 * field-api has answered with none ([listAnswered]).
 */
@Composable
fun SitePickScreen(
    personName: String,
    sites: List<SiteRef>,
    currentSiteId: String?,
    homes: List<HomeChoice>,
    selected: Home,
    onSite: (String) -> Unit,
    onHome: (Home) -> Unit,
    onContinue: () -> Unit,
    pairedSiteName: String? = null,
    /** SitePick.canContinue: field-api has answered the site list (an empty list then does not block Continue). */
    listAnswered: Boolean = false,
) {
    Column(
        Modifier.fillMaxSize().background(Ground).verticalScroll(rememberScrollState()).padding(start = 20.dp, end = 20.dp, top = 56.dp, bottom = 28.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Signed in as $personName", color = Muted, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
            Text("Where are you working?", color = Ink, fontSize = 28.sp, lineHeight = 34.sp, fontWeight = FontWeight.Bold,
                modifier = Modifier.semantics { heading() })
        }
        Column(Modifier.selectableGroup(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            val options = SitePick.options(sites, currentSiteId)
            when {
                options.isNotEmpty() -> options.forEach { o -> SiteRow(o.name, o.sub, o.sandbox, o.selected) { onSite(o.id) } }
                pairedSiteName != null -> SiteRow(pairedSiteName, "From the PC pairing", sandbox = false, selected = true, onClick = null)
                else -> Text("No site is listed for your account yet. Ask your SCMTIPS administrator to give you a Field site.",
                    color = Muted, fontSize = 15.sp, lineHeight = 22.sp)
            }
        }
        Column(Modifier.padding(top = 8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("What are you doing now?", color = Ink, fontSize = 18.sp, fontWeight = FontWeight.Bold, modifier = Modifier.semantics { heading() })
            Text(SitePick.roleNote(homes), color = Muted, fontSize = 14.sp, lineHeight = 20.sp)
        }
        Column(Modifier.selectableGroup(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            homes.chunked(2).forEach { pair ->
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    pair.forEach { c -> HomeTile(c, c.home == selected, Modifier.weight(1f)) { onHome(c.home) } }
                    if (pair.size == 1) Box(Modifier.weight(1f))
                }
            }
        }
        GradientButton("Continue", onContinue, enabled = SitePick.canContinue(sites, currentSiteId, pairedSiteName, listAnswered), modifier = Modifier.padding(top = 8.dp))
    }
}

@Composable
private fun SiteRow(name: String, sub: String, sandbox: Boolean, selected: Boolean, onClick: (() -> Unit)?) {
    val shape = CardShape
    Row(
        Modifier.fillMaxWidth().heightIn(min = 64.dp).background(Surface, shape)
            .border(if (selected) 2.dp else 1.dp, if (selected) BrandStart else Border, shape)
            .let { if (onClick != null) it.selectable(selected = selected, role = Role.RadioButton, onClick = onClick) else it }
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Box(Modifier.size(40.dp).background(if (sandbox) WarnBg else AccentTint, RoundedCornerShape(12.dp)), contentAlignment = Alignment.Center) {
            Glyph(GlyphKind.HOUSE, if (sandbox) SandboxInk else AccentInk, size = 20.dp)
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Text(name, color = Ink, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
            Text(sub, color = Muted, fontSize = 14.sp)
        }
        Box(Modifier.size(22.dp).border(2.dp, if (selected) BrandStart else Color(0xFF9CA3AF), CircleShape), contentAlignment = Alignment.Center) {
            if (selected) Box(Modifier.size(12.dp).background(BrandStart, CircleShape))
        }
    }
}

@Composable
private fun HomeTile(c: HomeChoice, selected: Boolean, modifier: Modifier, onClick: () -> Unit) {
    val shape = CardShape
    Column(
        modifier.heightIn(min = 92.dp).background(if (selected) AccentSelected else Surface, shape)
            .border(if (selected) 2.dp else 1.dp, if (selected) BrandStart else Border, shape)
            .selectable(selected = selected, role = Role.RadioButton, onClick = onClick).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(c.home.menuLabel, color = Ink, fontSize = 16.sp, fontWeight = FontWeight.Bold)
        Text(HomeBlurb.of(c.home), color = Color(0xFF4B5160), fontSize = 13.sp, lineHeight = 18.sp)
        if (!c.canAct) Tag(c.badge, Muted, QuietTint)
    }
}
