package com.scmtips.field.feature.decisions.flow

import com.scmtips.field.feature.decisions.api.StepUpMethod
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** A step-up code typed on the PHONE screen. Codes are never spoken and never logged. */
class StepUpEntry(val method: StepUpMethod, val code: String) {
    override fun toString(): String = "StepUpEntry(method=$method, code=<redacted>)"
    override fun equals(other: Any?): Boolean = other is StepUpEntry && other.method == method && other.code == code
    override fun hashCode(): Int = 31 * method.hashCode() + code.hashCode()
}

fun interface StepUpPrompter {
    /** Asks for an authenticator or backup code on the phone. Null when the person cancels. */
    suspend fun requestCode(retryMessage: String?): StepUpEntry?
}

/**
 * Bridges the flow's step-up request to whichever phone screen is showing (ported from the core's
 * wearable app ui/StepUpBroker): the screen watches [pending] and answers it once.
 */
class StepUpBroker(private val onRequested: () -> Unit = {}) : StepUpPrompter {
    class Pending(val retryMessage: String?, internal val answer: CompletableDeferred<StepUpEntry?>)

    private val _pending = MutableStateFlow<Pending?>(null)
    val pending: StateFlow<Pending?> = _pending.asStateFlow()

    override suspend fun requestCode(retryMessage: String?): StepUpEntry? {
        val p = Pending(retryMessage, CompletableDeferred())
        _pending.value = p
        onRequested()
        return try {
            p.answer.await()
        } finally {
            _pending.compareAndSet(p, null)
        }
    }

    /** The screen's answer: the code, or null for Cancel. Later answers to the same request are ignored. */
    fun answer(p: Pending, entry: StepUpEntry?) {
        p.answer.complete(entry)
    }
}
