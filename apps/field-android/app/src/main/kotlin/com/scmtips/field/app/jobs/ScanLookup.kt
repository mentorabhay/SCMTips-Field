package com.scmtips.field.app.jobs

/** "Scan anything" result: what the code is and which open jobs it starts (design: Scan tab). */
data class ScanResult(val kind: String, val code: String, val about: String, val actions: List<Pair<String, String>>)

object ScanLookup {
    /** [actions] pairs are (button label, task id). Only the operator's open tasks are searched. */
    fun lookup(code: String, tasks: List<JobTask>): ScanResult {
        val c = code.trim()
        val byBin = tasks.flatMap { t -> t.lines.filter { JobRunner.same(c, it.bin) }.map { t to it } }
        if (byBin.isNotEmpty()) {
            val materials = byBin.mapNotNull { it.second.material }.distinct()
            return ScanResult(
                "Bin", c,
                if (materials.isEmpty()) "A bin in your open jobs" else "In your jobs with ${materials.joinToString()}",
                byBin.map { it.first }.distinctBy { it.id }.map { actionFor(it) },
            )
        }
        val bySerial = tasks.flatMap { t -> t.lines.filter { JobRunner.same(c, it.expectedSerial) }.map { t to it } }
        if (bySerial.isNotEmpty()) {
            val l = bySerial.first().second
            return ScanResult(
                "Equipment serial", c,
                listOfNotNull(l.description ?: l.material, l.position).joinToString(" · "),
                bySerial.map { it.first }.distinctBy { it.id }.map { actionFor(it) },
            )
        }
        val byMaterial = tasks.flatMap { t -> t.lines.filter { JobRunner.same(c, it.material) }.map { t to it } }
        if (byMaterial.isNotEmpty()) {
            val l = byMaterial.first().second
            return ScanResult(
                "Product", c,
                l.description ?: "A product in your open jobs",
                byMaterial.map { it.first }.distinctBy { it.id }.map { actionFor(it) },
            )
        }
        val looksLikeBin = JobRunner.looksLikeBin(c)
        return ScanResult(
            if (looksLikeBin) "Bin" else "Code", c,
            "Not in any of your open jobs. Ask your supervisor if you expected it.",
            emptyList(),
        )
    }

    private fun actionFor(t: JobTask): Pair<String, String> = when (t.type) {
        JobType.RECEIVE -> "Receive ${t.refDocNo ?: t.title}"
        JobType.PUTAWAY -> "Put away here"
        JobType.PICK -> "Pick ${t.refDocNo ?: ""}".trim()
        JobType.COUNT -> if (t.isRecount) "Recount this bin" else "Count this bin"
        JobType.AUDIT -> "Audit this site"
        JobType.SWAP -> "Swap this unit"
    } to t.id
}
