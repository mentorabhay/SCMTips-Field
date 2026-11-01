package com.scmtips.field.app.ui.shell

import androidx.compose.runtime.Composable
import com.scmtips.field.app.AppUi
import com.scmtips.field.app.check.CheckAction
import com.scmtips.field.app.shell.Home
import com.scmtips.field.app.shell.ShellAction
import com.scmtips.field.app.shell.ShellPage
import com.scmtips.field.app.ui.Actions
import com.scmtips.field.app.ui.homes.ApprovalsHome
import com.scmtips.field.app.ui.homes.HomeModelsFromUi
import com.scmtips.field.app.ui.homes.ScanHome
import com.scmtips.field.app.ui.homes.TowerHome
import com.scmtips.field.app.ui.homes.WarehouseHome
import com.scmtips.field.app.ui.theme.LocalReduceMotion
import com.scmtips.field.app.ui.workSection

/**
 * THE HOME SEAM (docs/design/M5_UI_CONTRACT.md §1): builder B's home for [home], below the shell's header (switcher,
 * status pill, greeting, headline, view-only banner, connection card), callbacks bound per §4 (M5-U06). [canAct]
 * comes from the shell (HomeRules.canAct); every act button of a home is disabled when it is false. Warehouse and
 * Tower keep the work session card ("Start work") in their `extra` slot, only when the account can act there.
 */
@Composable
fun HomeContent(home: Home, ui: AppUi, a: Actions, canAct: Boolean) {
    val still = LocalReduceMotion.current
    when (home) {
        Home.WAREHOUSE -> WarehouseHome(
            model = HomeModelsFromUi.warehouse(ui),
            canAct = canAct,
            reduceMotion = still,
            onOpenTask = a.openTask,
            onOpenStarter = a.openStarter,
            onStartCase = a.startCase,
            onStartSandbox = a.startSandbox,
            onRefresh = a.refresh,
            extra = { if (canAct) workSection(ui, a) },
        )
        Home.TOWER -> TowerHome(
            model = HomeModelsFromUi.tower(ui),
            canAct = canAct,
            reduceMotion = still,
            onOpenTask = a.openTask,
            onRefresh = a.refresh,
            extra = { if (canAct) workSection(ui, a) },
        )
        Home.APPROVALS -> ApprovalsHome(
            model = HomeModelsFromUi.approvals(ui, nextDecision = ui.decisions.next, draftClaims = ui.claims.drafts),
            canAct = canAct,
            reduceMotion = still,
            onReviewDecisions = a.startReview,
            onReviewClaims = a.startClaims,
            onRefresh = { a.refreshDecisions(); a.refreshClaims() },
        )
        Home.SCAN -> ScanHome(
            model = HomeModelsFromUi.scan(ui),
            canAct = canAct,
            reduceMotion = still,
            onCheckBox = { a.check(CheckAction.START) },
            onOpenCheck = { a.check(CheckAction.START) },
            // Signed in with sites to choose from: Profile has the site's Change; a PC pairing has its one site.
            onLinkSite = if (ui.sites.isNotEmpty()) ({ a.shell(ShellAction.SelectTab(com.scmtips.field.app.shell.Tab.PROFILE)) }) else null,
        )
    }
}
