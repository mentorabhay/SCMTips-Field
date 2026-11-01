package com.scmtips.field.app.ui.shell

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.shell.Tab
import com.scmtips.field.app.ui.BackArrow
import com.scmtips.field.app.ui.CardShape
import com.scmtips.field.app.ui.MinTouch
import com.scmtips.field.app.ui.theme.BrandStart
import com.scmtips.field.app.ui.theme.Border
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.app.ui.theme.RowDivider
import com.scmtips.field.app.ui.theme.Surface
import com.scmtips.field.app.ui.theme.SwitchOff

/** "GLASSES AND VOICE"-style label above a settings group (prototype Settings.dc.html). */
@Composable
internal fun SectionLabel(text: String) {
    Text(text.uppercase(), fontSize = 13.sp, fontWeight = FontWeight.Bold, color = Muted, modifier = Modifier.padding(start = 4.dp, top = 4.dp))
}

/** A white 16 dp group of rows. */
@Composable
internal fun Group(content: @Composable ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxWidth().background(Surface, CardShape).border(1.dp, Border, CardShape), content = content)
}

@Composable
internal fun RowLine() = Box(Modifier.fillMaxWidth().height(1.dp).background(RowDivider))

/** A settings switch row; the whole row toggles (48 dp at least). */
@Composable
internal fun ToggleRow(title: String, sub: String, on: Boolean, onToggle: () -> Unit, last: Boolean = false) {
    Row(
        Modifier.fillMaxWidth().heightIn(min = MinTouch).clickable(role = Role.Switch, onClick = onToggle).padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = Ink)
            Text(sub, fontSize = 13.sp, color = Muted)
        }
        Switch(on, { onToggle() }, colors = SwitchDefaults.colors(checkedTrackColor = BrandStart, uncheckedTrackColor = SwitchOff,
            uncheckedThumbColor = Color.White, uncheckedBorderColor = SwitchOff))
    }
    if (!last) RowLine()
}

/** A row that opens something: title, optional sub line, optional action word on the right. */
@Composable
internal fun NavRow(title: String, sub: String? = null, action: String? = null, onClick: (() -> Unit)?, last: Boolean = false, ink: Color = Ink) {
    Row(
        Modifier.fillMaxWidth().heightIn(min = 56.dp)
            .let { if (onClick != null) it.clickable(role = Role.Button, onClick = onClick) else it }
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = ink)
            sub?.let { Text(it, fontSize = 13.sp, color = Muted) }
        }
        action?.let { Text(it, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = com.scmtips.field.app.ui.theme.AccentInk) }
    }
    if (!last) RowLine()
}

/** A page title with the round Back button of the prototype (Settings, Connections, Diagnostics). */
@Composable
internal fun PageHeader(title: String, onBack: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Box(
            Modifier.size(MinTouch).background(Surface, CircleShape).border(1.dp, Border, CircleShape)
                .clickable(role = Role.Button, onClick = onBack).semantics { contentDescription = "Back" },
            contentAlignment = Alignment.Center,
        ) { BackArrow(Ink) }
        Text(title, fontSize = 24.sp, fontWeight = FontWeight.Bold, color = Ink)
    }
}

/** The tab bar's line icons (24 dp, 2 dp stroke, as TabBar.dc.html), drawn so no icon library is needed. */
@Composable
internal fun TabGlyph(tab: Tab, color: Color, side: androidx.compose.ui.unit.Dp = 24.dp) = Canvas(Modifier.size(side)) {
    val w = size.width / 24f
    val stroke = Stroke(width = 2f * w, cap = StrokeCap.Round)
    fun p(block: Path.() -> Unit) = drawPath(Path().apply(block), color, style = stroke)
    when (tab) {
        Tab.HOME -> p { moveTo(3 * w, 11 * w); lineTo(12 * w, 4 * w); lineTo(21 * w, 11 * w); lineTo(21 * w, 20 * w); lineTo(15 * w, 20 * w)
            lineTo(15 * w, 14 * w); lineTo(9 * w, 14 * w); lineTo(9 * w, 20 * w); lineTo(3 * w, 20 * w); close() }
        Tab.ACTIVITY -> { drawCircle(color, 9 * w, style = stroke); p { moveTo(12 * w, 7 * w); lineTo(12 * w, 12 * w); lineTo(15 * w, 14 * w) } }
        Tab.SCAN -> scanCorners(w, color, stroke)
        Tab.INBOX -> { p { moveTo(4 * w, 13 * w); lineTo(6 * w, 5 * w); lineTo(18 * w, 5 * w); lineTo(20 * w, 13 * w); lineTo(20 * w, 19 * w); lineTo(4 * w, 19 * w); close() }
            p { moveTo(4 * w, 13 * w); lineTo(9 * w, 13 * w); lineTo(10 * w, 15 * w); lineTo(14 * w, 15 * w); lineTo(15 * w, 13 * w); lineTo(20 * w, 13 * w) } }
        Tab.PROFILE -> { drawCircle(color, 4 * w, Offset(12 * w, 8 * w), style = stroke)
            drawArc(color, 180f, 180f, false, Offset(4 * w, 13 * w), androidx.compose.ui.geometry.Size(16 * w, 16 * w), style = stroke) }
    }
}

private fun DrawScope.scanCorners(w: Float, color: Color, stroke: Stroke) {
    fun l(x1: Float, y1: Float, x2: Float, y2: Float) = drawLine(color, Offset(x1 * w, y1 * w), Offset(x2 * w, y2 * w), stroke.width, StrokeCap.Round)
    l(4f, 8f, 4f, 4f); l(4f, 4f, 8f, 4f); l(16f, 4f, 20f, 4f); l(20f, 4f, 20f, 8f)
    l(20f, 16f, 20f, 20f); l(20f, 20f, 16f, 20f); l(8f, 20f, 4f, 20f); l(4f, 20f, 4f, 16f); l(7f, 12f, 17f, 12f)
}
