package com.scmtips.field.app.home

import com.scmtips.field.app.jobs.JobRunner
import com.scmtips.field.app.jobs.JobTask
import com.scmtips.field.app.jobs.JobType
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.util.Base64

/** Who is signed in, from the core token's claims (never logged; only the name is kept). */
data class Person(val name: String, val initials: String) {
    companion object {
        val UNKNOWN = Person("Signed in", "?")

        /** Reads `name` or `sub` from the JWT payload; anything unreadable gives [UNKNOWN]. */
        fun fromCoreToken(token: String): Person {
            val payload = token.split('.').getOrNull(1) ?: return UNKNOWN
            val claims = runCatching {
                Json.parseToJsonElement(String(Base64.getUrlDecoder().decode(payload.padEnd((payload.length + 3) / 4 * 4, '=')))) as? JsonObject
            }.getOrNull() ?: return UNKNOWN
            val raw = (claims["name"] as? JsonPrimitive)?.contentOrNull ?: (claims["sub"] as? JsonPrimitive)?.contentOrNull
            return raw?.let(::fromName) ?: UNKNOWN
        }

        /** "asha.sharma" -> Asha Sharma / AS; "smoke-op" -> Smoke Op / SO; "ravi" -> Ravi / RA. */
        fun fromName(raw: String): Person? {
            val parts = raw.substringBefore('@').split('.', '_', '-', ' ').filter { it.isNotBlank() }
            if (parts.isEmpty()) return null
            val name = parts.joinToString(" ") { p -> p.replaceFirstChar { it.uppercase() } }
            val initials = if (parts.size >= 2) "${parts[0][0]}${parts[1][0]}" else parts[0].take(2)
            return Person(name, initials.uppercase())
        }
    }
}

/** One "Assigned to you" card (design: Main.dc.html Today). */
data class TaskCard(val taskId: String, val badge: String, val title: String, val sub: String, val flag: String?, val warm: Boolean)

/** One "Start something else" tile; [taskId] null when there is no open job of that kind. */
data class Starter(val label: String, val type: JobType, val taskId: String?)

object TodayModel {
    fun card(t: JobTask): TaskCard {
        val ref = t.refDocNo?.let(JobRunner::spokenDoc)
        val n = t.lines.size
        val title = when (t.type) {
            JobType.RECEIVE -> "Receive · ${ref?.let { "Delivery $it" } ?: t.title}"
            JobType.PUTAWAY -> "Put away · $n ${JobRunner.plural(n, "pallet")}"
            JobType.PICK -> "Pick · ${ref?.let { "Order $it" } ?: t.title}"
            JobType.COUNT -> "${if (t.isRecount) "Recount" else "Count"} bin ${t.lines.firstNotNullOfOrNull { it.bin } ?: ""}".trim()
            JobType.AUDIT -> "Site visit · ${t.title}"
            JobType.SWAP -> "Swap · ${t.title}"
        }
        val sub = t.subtitle ?: when (t.type) {
            JobType.RECEIVE -> "$n ${JobRunner.plural(n, "item")}"
            JobType.PUTAWAY -> "From the receiving dock"
            JobType.PICK -> "$n ${JobRunner.plural(n, "stop")}"
            JobType.COUNT -> t.reason ?: "$n ${JobRunner.plural(n, "product")}"
            JobType.AUDIT -> "$n ${JobRunner.plural(n, "unit")} to check"
            JobType.SWAP -> t.lines.firstOrNull()?.position ?: "Replace a unit"
        }
        val flag = when {
            t.isRecount -> "Today"
            !t.due.isNullOrBlank() -> "Due ${t.due}"
            t.status == "in_progress" -> "Started"
            else -> null
        }
        return TaskCard(t.id, badge(t), title, if (t.isRecount && t.subtitle == null) t.reason ?: sub else sub, flag, t.isRecount || !t.due.isNullOrBlank())
    }

    fun badge(t: JobTask): String = when (t.type) {
        JobType.RECEIVE -> "IN"
        JobType.PUTAWAY -> "PA"
        JobType.PICK -> "PK"
        JobType.COUNT -> if (t.isRecount) "RC" else "CT"
        JobType.AUDIT -> "TW"
        JobType.SWAP -> "SW"
    }

    /** Warehouse starters always; tower starters when the site has tower work. */
    fun starters(tasks: List<JobTask>): List<Starter> {
        fun first(type: JobType) = tasks.firstOrNull { it.type == type }?.id
        val warehouse = listOf(
            Starter("Receive", JobType.RECEIVE, first(JobType.RECEIVE)),
            Starter("Put away", JobType.PUTAWAY, first(JobType.PUTAWAY)),
            Starter("Pick", JobType.PICK, first(JobType.PICK)),
            Starter("Count a bin", JobType.COUNT, first(JobType.COUNT)),
        )
        val tower = listOf(
            Starter("Site visit", JobType.AUDIT, first(JobType.AUDIT)),
            Starter("Swap a unit", JobType.SWAP, first(JobType.SWAP)),
        )
        return if (tasks.any { it.type.isTower }) tower + warehouse else warehouse
    }

    fun noneOpen(type: JobType): String = when (type) {
        JobType.RECEIVE -> "No delivery to receive right now."
        JobType.PUTAWAY -> "Nothing to put away right now. A receipt creates put-away work."
        JobType.PICK -> "No order to pick right now."
        JobType.COUNT -> "No count is assigned right now."
        JobType.AUDIT -> "No site visit is assigned right now."
        JobType.SWAP -> "No swap is assigned right now."
    }
}

/** The connection chip on Today. */
enum class Link(val text: String) {
    CONNECTING("Connecting…"),
    ONLINE("Online · nothing waiting to send"),
    OFFLINE("Offline · cannot reach the PC"),
}
