package com.scmtips.field.app.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.jobs.Tone
import com.scmtips.field.app.ui.theme.CardBg
import com.scmtips.field.app.ui.theme.Danger
import com.scmtips.field.app.ui.theme.DangerBg
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.theme.Line
import com.scmtips.field.app.ui.theme.LineStrong
import com.scmtips.field.app.ui.theme.Primary
import com.scmtips.field.app.ui.theme.Success
import com.scmtips.field.app.ui.theme.SuccessBg
import com.scmtips.field.app.ui.theme.SuccessInk
import com.scmtips.field.app.ui.theme.WarnBg
import com.scmtips.field.app.ui.theme.WarnInk

val Corner = RoundedCornerShape(8.dp)

/** White card with a 1 dp line and 8 dp corners (design). */
@Composable
fun CardBox(
    modifier: Modifier = Modifier,
    bg: Color = CardBg,
    line: Color = Line,
    padding: PaddingValues = PaddingValues(16.dp),
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier.fillMaxWidth().background(bg, Corner).border(1.dp, line, Corner).padding(padding),
        verticalArrangement = Arrangement.spacedBy(4.dp),
        content = content,
    )
}

@Composable
fun PrimaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true,
                  bg: Color = Primary, fg: Color = Color.White, height: Dp = 58.dp) {
    Button(
        onClick = onClick, enabled = enabled, shape = Corner,
        modifier = modifier.fillMaxWidth().height(height),
        colors = ButtonDefaults.buttonColors(containerColor = bg, contentColor = fg,
            disabledContainerColor = bg.copy(alpha = 0.45f), disabledContentColor = fg.copy(alpha = 0.8f)),
    ) { Text(text, fontSize = 18.sp, fontWeight = FontWeight.Bold) }
}

@Composable
fun SecondaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, ink: Color = Ink, line: Color = Line, enabled: Boolean = true) {
    OutlinedButton(
        onClick = onClick, enabled = enabled, shape = Corner, border = BorderStroke(1.dp, line),
        modifier = modifier.fillMaxWidth().height(52.dp),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = ink),
    ) { Text(text, fontSize = 17.sp, fontWeight = FontWeight.Bold) }
}

/** The small "Change" / "Turn on" buttons of the design, at least 48 dp tall. */
@Composable
fun SmallButton(text: String, onClick: () -> Unit, enabled: Boolean = true) {
    OutlinedButton(
        onClick = onClick, enabled = enabled, shape = RoundedCornerShape(6.dp), border = BorderStroke(1.dp, LineStrong),
        modifier = Modifier.heightIn(min = 48.dp), contentPadding = PaddingValues(horizontal = 12.dp),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = Primary),
    ) { Text(text, fontWeight = FontWeight.Bold, fontSize = 15.sp) }
}

@Composable
fun Chip(text: String, bg: Color, fg: Color, dot: Color? = null, line: Color? = null) {
    Row(
        Modifier.background(bg, RoundedCornerShape(999.dp))
            .let { if (line != null) it.border(1.dp, line, RoundedCornerShape(999.dp)) else it }
            .padding(horizontal = 10.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        dot?.let { Box(Modifier.size(8.dp).background(it, CircleShape)) }
        Text(text, color = fg, fontSize = 13.sp, fontWeight = if (dot != null) FontWeight.Bold else FontWeight.Normal)
    }
}

@Composable
fun Avatar(initials: String, size: Dp = 44.dp) {
    Box(Modifier.size(size).background(Primary, CircleShape), contentAlignment = Alignment.Center) {
        Text(initials, color = Color.White, fontWeight = FontWeight.Bold, fontSize = 16.sp)
    }
}

/** An inline notice in the tone the runner asks for. */
@Composable
fun Notice(text: String, tone: Tone) {
    val (bg, fg) = when (tone) {
        Tone.GOOD -> SuccessBg to SuccessInk
        Tone.WARN -> WarnBg to WarnInk
        Tone.BAD -> DangerBg to Danger
        Tone.NEUTRAL -> WarnBg.copy(alpha = 0.6f) to Ink
    }
    Text(text, color = fg, fontSize = 15.sp, modifier = Modifier.fillMaxWidth().background(bg, Corner).padding(horizontal = 14.dp, vertical = 10.dp))
}

@Composable
fun BackArrow(color: Color) = Canvas(Modifier.size(24.dp)) {
    val p = Path().apply {
        moveTo(size.width * 0.62f, size.height * 0.2f)
        lineTo(size.width * 0.33f, size.height * 0.5f)
        lineTo(size.width * 0.62f, size.height * 0.8f)
    }
    drawPath(p, color, style = Stroke(width = 2.2.dp.toPx(), cap = StrokeCap.Round))
}

@Composable
fun BarcodeGlyph(color: Color = Color.White) = Canvas(Modifier.size(40.dp)) {
    val xs = listOf(0.17f, 0.33f, 0.46f, 0.62f, 0.75f, 0.83f)
    xs.forEach { x ->
        drawLine(color, Offset(size.width * x, size.height * 0.25f), Offset(size.width * x, size.height * 0.75f),
            strokeWidth = 1.8.dp.toPx(), cap = StrokeCap.Round)
    }
}

@Composable
fun CheckGlyph(color: Color = Color.White, side: Dp = 44.dp) = Canvas(Modifier.size(side)) {
    val p = Path().apply {
        moveTo(size.width * 0.21f, size.height * 0.5f)
        lineTo(size.width * 0.42f, size.height * 0.71f)
        lineTo(size.width * 0.79f, size.height * 0.29f)
    }
    drawPath(p, color, style = Stroke(width = 2.6.dp.toPx(), cap = StrokeCap.Round))
}

@Composable
fun DoneBadge() {
    Box(Modifier.size(84.dp).background(Success, CircleShape), contentAlignment = Alignment.Center) { CheckGlyph() }
}
