package com.scmtips.field.feature.decisions.flow

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.launch

/** One "Hey Meta, start SCMTips Field" launch from the glasses (Meta's voice invocation); answer it once. */
class LaunchRequest(
    private val success: suspend (String) -> Boolean,
    private val failure: suspend (String) -> Boolean,
) {
    suspend fun accept(message: String): Boolean = success(message)
    suspend fun decline(message: String): Boolean = failure(message)
}

/**
 * Answers app launches said to Meta AI on the glasses and starts a decision review (ported from the
 * core's wearable app). "Hey Meta" itself is Meta's: the glasses hand it to Meta AI, which may launch
 * the app; the app never hears or intercepts the wake word.
 */
class LaunchCoordinator(
    private val launches: Flow<LaunchRequest>,
    private val scope: CoroutineScope,
    private val canReview: () -> Boolean,
    private val startReview: () -> Unit,
) {
    fun start(): Job = scope.launch {
        launches.collect { launch ->
            if (canReview()) {
                launch.accept(MSG_OPENING)
                startReview()
            } else {
                launch.decline(MSG_NOT_SIGNED_IN)
            }
        }
    }

    companion object {
        const val MSG_OPENING = "Opening SCMTips Field decisions."
        const val MSG_NOT_SIGNED_IN = "SCMTips Field is not signed in as an approver. Open the app on your phone to sign in."
    }
}
