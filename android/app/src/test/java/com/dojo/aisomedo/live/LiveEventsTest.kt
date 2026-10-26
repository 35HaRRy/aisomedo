package com.dojo.aisomedo.live

import com.dojo.aisomedo.api.DojoApi
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import okhttp3.Call
import okhttp3.EventListener
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.TimeUnit

class LiveEventsTest {
    @Test fun streamSurvivesFragmentedFrames() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setHeader("Content-Type", "text/event-stream")
                .setBody(": bağlı\r\nevent: ready\r\ndata: {\r\ndata: \"protocol\":1}\r\n\r\nevent: heartbeat\ndata: {}\n\nevent: opaque\ndata: not json\n\nevent: change\ndata: {\"event_id\":\"ş\",\"versions\":{\"package:1\":2}}\n\n")
                .throttleBody(1, 1, TimeUnit.MILLISECONDS))
            val events = withTimeout(5_000) { api(server).liveEvents().toList() }
            assertEquals(listOf("ready", "heartbeat", "change"), events.map { it.type })
            assertEquals(1, events.first().protocol)
            assertEquals("ş", events.last().eventId)
            assertEquals(mapOf("package:1" to 2L), events.last().versions)
            val request = server.takeRequest()
            assertEquals("/api/events", request.path)
            assertEquals("Bearer DEVICE", request.getHeader("Authorization"))
            assertEquals("5", request.getHeader("X-Android-Version-Code"))
        }
    }

    @Test fun rejectsOversizedIncompleteAndInvalidUtf8Frames() = runBlocking {
        for (body in listOf(
            ("data: " + "x".repeat(65_536) + "\n\n").toByteArray(),
            "event: ready\ndata: {\"protocol\":1}".toByteArray(),
            byteArrayOf(0xc3.toByte(), 0x28, 10, 10),
        )) MockWebServer().use { server ->
            server.enqueue(MockResponse().setHeader("Content-Type", "text/event-stream").setBody(okio.Buffer().write(body)))
            assertNotNull(runCatching { api(server).liveEvents().toList() }.exceptionOrNull())
        }
    }

    @Test fun cancellationClosesBlockedSocketAndOnlyStreamHasUnlimitedCallDeadline() = runBlocking {
        MockWebServer().use { server ->
            val cancelled = CompletableDeferred<Unit>()
            val deadlines = mutableListOf<Pair<Int, Long>>()
            val http = OkHttpClient.Builder().eventListener(object : EventListener() {
                override fun canceled(call: Call) { cancelled.complete(Unit) }
            }).addInterceptor { chain ->
                deadlines.add(chain.readTimeoutMillis() to chain.call().timeout().timeoutNanos())
                chain.proceed(chain.request())
            }.build()
            server.enqueue(MockResponse().setHeader("Content-Type", "text/event-stream")
                .setBody("event: ready\ndata: {\"protocol\":1}\n\n" + " ".repeat(100))
                .throttleBody(36, 1, TimeUnit.SECONDS))
            val ready = CompletableDeferred<Unit>()
            val api = api(server, http)
            val job = launch { api.liveEvents().collect { ready.complete(Unit) } }
            withTimeout(5_000) { ready.await() }
            withTimeout(2_000) { job.cancelAndJoin(); cancelled.await() }
            server.enqueue(MockResponse().setBody("{}")); api.request("GET", "/api/dashboard")
            assertEquals(listOf(45_000 to 0L, 10_000 to 30_000_000_000L), deadlines)
        }
    }

    private fun api(server: MockWebServer, http: OkHttpClient = OkHttpClient()) =
        DojoApi(server.url("/").toString().trimEnd('/'), "DEVICE", 5, http)
}
