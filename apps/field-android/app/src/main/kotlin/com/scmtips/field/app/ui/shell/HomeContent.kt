package com.scmtips.field.app.ui.shell

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.AppUi
import com.scmtips.field.app.check.CheckText
import com.scmtips.field.app.home.SandboxStart
import com.scmtips.field.app.home.TodayModel
import com.scmtips.field.app.shell.Home
import com.scmtips.field.app.shell.HomeRules
import com.scmtips.field.app.shell.ShellAction
import com.scmtips.field.app.shell.Tab
import com.scmtips.field.app.ui.Actions
import com.scmtips.field.app.ui.CardBox
import com.scmtips.field.app.ui.CountShelfDialog
import com.scmtips.field.app.ui.SecondaryButton
import com.scmtips.field.app.ui.assignedSections
import com.scmtips.field.app.ui.caseSection
import com.scmtips.field.app.ui.checkSection
import com.scmtips.field.app.ui.claimsSection
import com.scmtips.field.app.ui.decisionsSection
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.app.ui.workSection

/**
 * THE HOME SEAM (docs/design/M5_UI_CONTRACT.md §1): the content of [home] below the shell's header. To use builder B's
 * homes, replace one `Interim…Home(...)` call per branch with B's `WarehouseHome(model, canAct, …)` and its callbacks.
 */
@Composable
fun HomeContent(home: Home, ui: AppUi, a: Actions, canAct: Boolean) {
    when (home) {
        Home.WAREHOUSE -> InterimWarehouseHome(ui, a, canAct)
        Home.TOWER -> InterimTowerHome(ui, a, canAct)
        Home.APPROVALS -> InterimApprovalsHome(ui, a, canAct)
        Home.SCAN -> InterimScanHome(ui, a)
    }
}

// INTERIM homes (builder A, until builder B's ui/homes/* are merged): Today's own sections, split by home.

@Composable
private fun HomeList(content: LazyListScope.() -> Unit) {
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        content = content,
    )
}

private fun LazyListScope.emptyCard(title: String, body: String) = item {
    CardBox {
        Text(title, fontWeight = FontWeight.Bold, color = Ink)
        Text(body, color = Muted, fontSize = 14.sp)
    }
}

/** INTERIM Warehouse: work session, the sandbox test cases, warehouse jobs assigned to you, sandbox starters. */
@Composable
internal fun InterimWarehouseHome(ui: AppUi, a: Actions, canAct: Boolean) {
    var askShelf by remember { mutableStateOf(false) }
    if (askShelf) CountShelfDialog(onStart = { bin -> askShelf = false; a.startSandbox(SandboxStart.COUNT_SHELF, bin) }, onDismiss = { askShelf = false })
    val tasks = HomeRules.warehouseTasks(ui.tasks)
    HomeList {
        if (!canAct) {
            emptyCard("No warehouse work on this account", "Receipts, put-aways, picks and counts appear here for an operator account.")
            return@HomeList
        }
        workSection(ui, a)
        caseSection(ui, a)
        assignedSections(ui, a, tasks, TodayModel.starters(tasks).filterNot { it.type.isTower }) { askShelf = true }
    }
}

/** INTERIM Tower: the check-in state, then site visits and swaps assigned to you. */
@Composable
internal fun InterimTowerHome(ui: AppUi, a: Actions, canAct: Boolean) {
    val tasks = HomeRules.towerTasks(ui.tasks)
    HomeList {
        if (ui.visitId != null) emptyCard("On site · checked in", "Open the site visit to check out before you leave.")
        if (!canAct || tasks.isEmpty()) {
            emptyCard("No tower jobs assigned", "Site visits and unit swaps appear here when they are assigned to this phone.")
            return@HomeList
        }
        workSection(ui, a)
        assignedSections(ui, a, tasks, TodayModel.starters(tasks).filter { it.type.isTower }, askShelf = {}, sandboxStarters = false)
    }
}

/** INTERIM Approvals: the decisions card and the supervisor's claims card. */
@Composable
internal fun InterimApprovalsHome(ui: AppUi, a: Actions, canAct: Boolean) {
    HomeList {
        decisionsSection(ui, a)
        claimsSection(ui, a)
        if (!canAct && ui.claims.waiting == null) {
            emptyCard("No approvals on this account", "Decisions from SCMTIPS appear here for an approver account.")
        } else if (!ui.home.decisions && ui.claims.waiting == null) {
            emptyCard("Nothing waiting", "Decisions and claims appear here when they wait for you.")
        }
    }
}

/** INTERIM Scan product: the box check card, and the Scan tab for any code. */
@Composable
internal fun InterimScanHome(ui: AppUi, a: Actions) {
    HomeList {
        checkSection(ui, a)
        if (!CheckText.cardVisible(ui.pairing != null && ui.deviceId != null, ui.check.allowed)) {
            emptyCard(
                "Box checks are not available here",
                if (ui.pairing == null || ui.deviceId == null) "Box checks start once this phone is linked to a field site."
                else "The field server does not allow box checks for this account at this site.",
            )
        }
        item {
            CardBox {
                Text("Scan anything", fontWeight = FontWeight.Bold, color = Ink)
                Text("A bin, a box, a pallet or a serial number: the app says what it is and which of your jobs it starts.", color = Muted, fontSize = 14.sp)
                SecondaryButton("Open Scan", { a.shell(ShellAction.SelectTab(Tab.SCAN)) }, Modifier)
            }
        }
    }
}
