package com.dojo.aisomedo.live

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.io.PushbackInputStream
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction

@Serializable
data class LiveEvent(
    val type: String = "message",
    val protocol: Int? = null,
    @SerialName("event_id") val eventId: String? = null,
    val versions: Map<String, Long> = emptyMap(),
    val reason: String? = null,
)

/** Bounded wire parser; the caller owns socket cancellation and the IO dispatcher. */
internal suspend fun readLiveEvents(input: InputStream, emit: suspend (LiveEvent) -> Unit) {
    val source = PushbackInputStream(input.buffered(), 1)
    val json = Json { ignoreUnknownKeys = true }
    var type = "message"; val data = mutableListOf<String>(); var bytes = 0
    while (true) {
        val line = ByteArrayOutputStream()
        var eof = false
        while (true) {
            val byte = source.read()
            if (byte == -1) { eof = true; break }
            require(++bytes <= 65_536) { "Live frame too large" }
            if (byte == 13) {
                val next = source.read()
                if (next == 10) require(++bytes <= 65_536) { "Live frame too large" }
                else if (next != -1) source.unread(next)
                break
            }
            if (byte == 10) break
            line.write(byte)
        }
        if (eof) { require(bytes == 0) { "Incomplete live frame" }; return }
        val text = Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(line.toByteArray())).toString()
        if (text.isEmpty()) {
            if (data.isNotEmpty() && type in setOf("ready", "heartbeat", "change", "resync")) {
                emit(json.decodeFromString<LiveEvent>(data.joinToString("\n")).copy(type = type))
            }
            type = "message"; data.clear(); bytes = 0
        } else if (!text.startsWith(":")) {
            val field = text.substringBefore(':')
            val value = text.substringAfter(':', "").removePrefix(" ")
            if (field == "event") type = value
            if (field == "data") data.add(value)
        }
    }
}
