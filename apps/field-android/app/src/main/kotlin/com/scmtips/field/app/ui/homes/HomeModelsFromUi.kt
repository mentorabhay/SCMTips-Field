package com.scmtips.field.app.ui.homes

import com.scmtips.field.app.AppUi
import com.scmtips.field.app.look.Claim
import com.scmtips.field.feature.decisions.api.NextItem

/**
 * AppUi → the homes' models: field reads only, every rule is in the JVM-tested builders of HomeModels.kt. This file
 * is Android-bound only because AppUi lives in FieldController.kt. "Linked" means paired with a Field site, as Today.
 */
object HomeModelsFromUi {
    fun warehouse(ui: AppUi): WarehouseHomeModel =
        WarehouseHomeModel.of(ui.tasks, ui.sandbox, ui.home.fieldWork, linked = ui.pairing != null, loading = ui.loading)

    fun tower(ui: AppUi): TowerHomeModel =
        TowerHomeModel.of(ui.tasks, ui.pairing?.siteId, ui.visitId, ui.visitSiteId, linked = ui.pairing != null, loading = ui.loading)

    /**
     * AppUi keeps only the counts today ([AppUi.decisions].waiting, [AppUi.claims].waiting); pass the core's next item
     * and field-api's draft list when FieldController keeps them, and the cards get their real titles.
     */
    fun approvals(ui: AppUi, nowMs: Long = System.currentTimeMillis(), nextDecision: NextItem? = null, draftClaims: List<Claim>? = null): ApprovalsHomeModel =
        ApprovalsHomeModel.of(ui.decisions.waiting, ui.claims.waiting, nextDecision, draftClaims, approver = ui.home.decisions, nowMs = nowMs)

    /** Today's card rule (CheckText.cardVisible): linked to a site with a registered phone, and no 403 yet. */
    fun scan(ui: AppUi): ScanHomeModel = ScanHomeModel.of(ui.pairing != null && ui.deviceId != null, ui.check.allowed, ui.check.state)
}
