package com.scmtips.field.app.ui.homes

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.ui.theme.AccentInk
import com.scmtips.field.app.ui.theme.AccentTint
import com.scmtips.field.app.ui.theme.Border
import com.scmtips.field.app.ui.theme.BrandStart
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.MinTouch
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.app.ui.theme.Surface
import com.scmtips.field.app.ui.theme.WarnBg
import com.scmtips.field.app.ui.theme.Warning

/**
 * 4.1 Approvals home (ApprovalsInbox.dc.html), under the shell's header: Refresh, the All / Decisions / Claims
 * filter with real counts, the integrator's [extra] items (e.g. the running review's card), then one card per waiting
 * item (decisions by time left, then claims newest first; box-check claims are marked BOX CHECK). A tap starts the
 * voice review of that kind ([onReviewDecisions] / [onReviewClaims]), as Today's cards do. When AppUi has only counts the cards are honest summaries ("2 decisions waiting").
 */
@Composable
fun ApprovalsHome(
    model: ApprovalsHomeModel,
    canAct: Boolean,
    reduceMotion: Boolean,
    onReviewDecisions: () -> Unit,
    onReviewClaims: () -> Unit,
    onRefresh: () -> Unit,
    modifier: Modifier = Modifier,
    contentPadding: PaddingValues = PaddingValues(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 24.dp),
    extra: LazyListScope.() -> Unit = {},
) {
    var filter by rememberSaveable { mutableStateOf(ApprovalFilter.ALL) }
    val shown = model.shown(filter)
    LazyColumn(modifier.fillMaxSize(), contentPadding = contentPadding, verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { RefreshRow(loading = false, onRefresh = onRefresh) }
        if (!model.empty || model.checking) item {
            Row(Modifier.selectableGroup().padding(bottom = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ApprovalFilter.entries.forEach { f -> FilterChip(model.chip(f), f == filter) { filter = f } }
            }
        }
        extra()
        when {
            model.checking -> item {
                Row(Modifier.fillMaxWidth().padding(vertical = 12.dp), verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    CircularProgressIndicator(Modifier.size(22.dp), color = BrandStart, strokeWidth = 2.5.dp)
                    Text("Asking SCMTIPS what waits for you…", color = Muted, fontSize = 15.sp)
                }
            }
            model.empty -> item {
                EmptyState("Nothing is waiting for your approval. New decisions and claims appear here.", "Refresh", onRefresh, enabled = true) {
                    EmptyInboxArt(reduceMotion)
                }
            }
            shown.isEmpty() -> item {
                Text(if (filter == ApprovalFilter.CLAIMS) "No claims waiting." else "No decisions waiting.", color = Muted, fontSize = 15.sp,
                    modifier = Modifier.padding(vertical = 12.dp))
            }
        }
        items(shown, key = { it.key }) { item -> ItemCard(item, canAct) { if (item.target == ApprovalTarget.DECISIONS) onReviewDecisions() else onReviewClaims() } }
        if (!model.empty) item {
            Text("In a work session you can also say “decisions” or “claims”.", color = Muted, fontSize = 13.sp,
                modifier = Modifier.padding(top = 6.dp))
        }
    }
}

@Composable
private fun FilterChip(label: String, selected: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(18.dp)
    Box(
        Modifier.heightIn(min = MinTouch).selectable(selected = selected, role = Role.Tab, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, color = if (selected) Color.White else Ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
            modifier = Modifier.background(if (selected) Ink else Surface, shape).border(1.dp, if (selected) Ink else Border, shape)
                .padding(horizontal = 14.dp, vertical = 8.dp))
    }
}

@Composable
private fun ItemCard(item: ApprovalItem, canAct: Boolean, onClick: () -> Unit) {
    val (ink, bg) = when (item.kind) {
        ApprovalKind.DECISION -> AccentInk to AccentTint
        ApprovalKind.CLAIM, ApprovalKind.BOX_CHECK -> SandboxInk to WarnBg
    }
    HomeCard(onClick = onClick, enabled = canAct, shape = RoundedCornerShape(18.dp), padding = PaddingValues(horizontal = 16.dp, vertical = 14.dp),
        onClickLabel = if (item.target == ApprovalTarget.DECISIONS) "Hear the decision" else "Hear the claims") {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Tag(item.kind.label, ink, bg)
            Box(Modifier.weight(1f))
            Text(item.time, color = if (item.urgent) Warning else Muted, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
        }
        Text(item.title, color = Ink, fontSize = 17.sp, lineHeight = 23.sp, fontWeight = FontWeight.Bold)
        Text(item.sub, color = Muted, fontSize = 14.sp)
    }
}
