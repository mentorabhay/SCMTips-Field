package com.scmtips.field.app.shell

import com.scmtips.field.app.jobs.JobTask

/**
 * The four homes of the redesign (blueprint, A-07; docs/design/M5_UI_CONTRACT.md §2). The role switcher at the top of
 * every home always lists all four, in this order; each is "can act" or "view only" for the signed-in account.
 */
enum class Home(val key: String, val label: String, val menuLabel: String, val cannotDo: String) {
    WAREHOUSE("warehouse", "Warehouse", "Warehouse work", "warehouse work"),
    TOWER("tower", "Tower", "Tower work", "tower work"),
    APPROVALS("approvals", "Approvals", "Approvals", "approvals"),
    SCAN("scan", "Scan product", "Scan a product", "product checks"),
    ;

    companion object {
        fun ofKey(key: String?): Home? = entries.firstOrNull { it.key == key }
    }
}

/**
 * What the account may do, from the app's existing state only: [fieldOperator] is HomeSections.fieldWork (a core
 * account with a Field role, or a QR pairing), [approver] is HomeSections.decisions, [towerTasks] is "tower jobs
 * (site visit, swap) are assigned to this phone" (there is no technician flag on the phone).
 */
data class Capabilities(
    val fieldOperator: Boolean,
    val approver: Boolean,
    val towerTasks: Boolean,
    /**
     * M5-U06: field-api lets this person decide draft claims (AppUi.claims.waiting is non-null only for a supervisor,
     * field.claim.decide). A field supervisor who is not a SCMTIPS approver acts on the Approvals home's claims.
     */
    val claimsDecider: Boolean = false,
)

/** One line of the role switcher. */
data class HomeChoice(val home: Home, val canAct: Boolean) {
    val badge: String get() = if (canAct) "can act" else "view only"
}

object HomeRules {
    /** The order "the first home the account can act in" is looked for (operator first, then approver). */
    private val PREFERENCE = listOf(Home.WAREHOUSE, Home.APPROVALS, Home.TOWER, Home.SCAN)

    fun canAct(home: Home, c: Capabilities): Boolean = when (home) {
        Home.WAREHOUSE -> c.fieldOperator
        Home.TOWER -> c.towerTasks
        Home.APPROVALS -> c.approver || c.claimsDecider
        Home.SCAN -> true // any Field role may check a box; the server's 403 hides the card itself
    }

    /** Always all four homes, in [Home] order: a reviewer can open every home and see why it is view only. */
    fun choices(c: Capabilities): List<HomeChoice> = Home.entries.map { HomeChoice(it, canAct(it, c)) }

    /** Operator -> Warehouse; approver only -> Approvals; else Scan product. */
    fun defaultHome(c: Capabilities): Home = PREFERENCE.first { canAct(it, c) }

    /** The banner of a view-only home; null when the account can act there. Never fake data, only this sentence. */
    fun viewOnlyBanner(home: Home, c: Capabilities): String? {
        if (canAct(home, c)) return null
        val who = when (home) {
            Home.APPROVALS -> "an approver"
            Home.TOWER -> "a technician with tower tasks"
            else -> "an operator"
        }
        return "View only: your account can't do ${home.cannotDo} here. Sign in as $who (e.g. tester01) to act."
    }

    /** The big line of a home's header, from real counts only (null counts: not asked yet). */
    fun headline(home: Home, warehouseTasks: Int, towerTasks: Int, decisionsWaiting: Int?, claimsWaiting: Int?, canAct: Boolean): String {
        fun n(k: Int, one: String, many: String) = "$k ${if (k == 1) one else many}"
        if (!canAct && home != Home.SCAN) return home.menuLabel
        return when (home) {
            Home.WAREHOUSE -> if (warehouseTasks == 0) "Nothing assigned yet" else n(warehouseTasks, "task", "tasks") + " today"
            Home.TOWER -> if (towerTasks == 0) "No tower jobs yet" else n(towerTasks, "tower job", "tower jobs") + " today"
            Home.APPROVALS -> {
                val d = decisionsWaiting ?: 0
                val c = claimsWaiting ?: 0
                when {
                    decisionsWaiting == null && claimsWaiting == null -> "Your decisions"
                    d + c == 0 -> "Nothing waiting"
                    else -> n(d + c, "item", "items") + " waiting"
                }
            }
            Home.SCAN -> "Scan a product"
        }
    }

    /** Tower homes show site visits and swaps; warehouse homes show the rest. */
    fun towerTasks(tasks: List<JobTask>): List<JobTask> = tasks.filter { it.type.isTower }
    fun warehouseTasks(tasks: List<JobTask>): List<JobTask> = tasks.filterNot { it.type.isTower }
}

/**
 * The chosen home, remembered in SharedPreferences together with who chose it, so another account (or a QR pairing)
 * starts at its own default. Nothing is stored until the person picks a home in the switcher.
 */
object HomeMemory {
    private const val SEP = '\u001F'

    /** A stable, non-secret name for the account: its e-mail, else its display name, else the PC pairing's tenant. */
    fun who(email: String?, name: String?, pairedApi: String?, pairedTenant: String?): String? =
        email?.trim()?.lowercase()?.takeIf { it.isNotEmpty() }
            ?: name?.trim()?.takeIf { it.isNotEmpty() }?.let { "name:$it" }
            ?: if (pairedApi != null && pairedTenant != null) "pc:$pairedApi#$pairedTenant" else null

    fun encode(who: String?, home: Home): String = "${who.orEmpty()}$SEP${home.key}"

    /** The stored home when it was chosen by [who]; null otherwise. */
    fun decode(stored: String?, who: String?): Home? {
        val s = stored ?: return null
        val i = s.lastIndexOf(SEP)
        if (i < 0) return null
        return if (s.substring(0, i) == who.orEmpty()) Home.ofKey(s.substring(i + 1)) else null
    }

    /** The home to open: the one [who] chose (can act or view only), else the account's default. */
    fun current(stored: String?, who: String?, c: Capabilities): Home = decode(stored, who) ?: HomeRules.defaultHome(c)
}
