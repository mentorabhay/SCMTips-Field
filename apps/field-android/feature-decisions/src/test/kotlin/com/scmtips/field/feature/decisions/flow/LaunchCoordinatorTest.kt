package com.scmtips.field.feature.decisions.flow

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.yield
import org.junit.Assert.assertEquals
import org.junit.Test

/** Ported from the core's wearable app (flow/LaunchCoordinatorTest), without kotlinx-coroutines-test. */
class LaunchCoordinatorTest {
    private suspend fun untilSubscribed(f: MutableSharedFlow<*>) = withTimeout(5_000) { while (f.subscriptionCount.value == 0) yield() }

    @Test
    fun aLaunchFromTheGlasses_isAcknowledged_andStartsTheReview() = runBlocking {
        val launches = MutableSharedFlow<LaunchRequest>(extraBufferCapacity = 4)
        var started = 0
        val replies = mutableListOf<String>()
        val job = LaunchCoordinator(launches, CoroutineScope(Dispatchers.Unconfined), canReview = { true }, startReview = { started++ }).start()
        untilSubscribed(launches)
        launches.emit(LaunchRequest(success = { replies += "ok:$it"; true }, failure = { replies += "fail:$it"; true }))
        withTimeout(5_000) { while (started == 0) yield() }
        assertEquals(1, started)
        assertEquals(listOf("ok:${LaunchCoordinator.MSG_OPENING}"), replies)
        job.cancel()
    }

    @Test
    fun aLaunchWhileNotSignedInAsApprover_isDeclined() = runBlocking {
        val launches = MutableSharedFlow<LaunchRequest>(extraBufferCapacity = 4)
        var started = 0
        val replies = mutableListOf<String>()
        val job = LaunchCoordinator(launches, CoroutineScope(Dispatchers.Unconfined), canReview = { false }, startReview = { started++ }).start()
        untilSubscribed(launches)
        launches.emit(LaunchRequest(success = { replies += "ok"; true }, failure = { replies += "fail:$it"; true }))
        withTimeout(5_000) { while (replies.isEmpty()) yield() }
        assertEquals(0, started)
        assertEquals(listOf("fail:${LaunchCoordinator.MSG_NOT_SIGNED_IN}"), replies)
        job.cancel()
    }
}
