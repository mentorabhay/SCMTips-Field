package com.scmtips.field.core.voice

import com.scmtips.field.core.outbox.api.UUIDv7
import com.scmtips.field.core.voice.grammar.ParsedUtterance

data class VoiceEventRecord(
    val id: String = UUIDv7.generate(),
    val taskId: String,
    val captureId: String?,
    val transcript: String,
    val confidence: Float,
    val intent: String,
    val isAccepted: Boolean,
    val locale: String = "en-US",
    val timestampMs: Long = System.currentTimeMillis()
)

/**
 * Records every utterance as an append-only voice_event for outbox relay
 * (Task T2.037 / FR2.038 / TC2.139).
 * Audio bytes are NEVER recorded or transmitted.
 */
class VoiceEventRecorder(
    private val outboxSink: (VoiceEventRecord) -> Unit = {},
    private val clock: () -> Long = System::currentTimeMillis,
) {
    private val recordedEvents = mutableListOf<VoiceEventRecord>()

    fun recordUtterance(
        taskId: String,
        captureId: String?,
        utterance: ParsedUtterance,
        locale: String = "en-US"
    ): VoiceEventRecord {
        val record = VoiceEventRecord(
            taskId = taskId,
            captureId = captureId,
            transcript = utterance.rawTranscript,
            confidence = utterance.confidence,
            intent = utterance.intent.name,
            isAccepted = utterance.isAccepted,
            locale = locale,
            timestampMs = clock()
        )

        synchronized(recordedEvents) {
            recordedEvents.add(record)
        }

        outboxSink(record)
        return record
    }

    fun getRecordedEvents(): List<VoiceEventRecord> = synchronized(recordedEvents) {
        recordedEvents.toList()
    }
}
