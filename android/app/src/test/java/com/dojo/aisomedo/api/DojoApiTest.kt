package com.dojo.aisomedo.api

import kotlinx.coroutines.*
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.*
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.TimeUnit
import java.nio.file.Files
import java.io.IOException
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicInteger

class DojoApiTest {
    @Test fun uploadRequestsWaitWithoutTransferDeadlinesButKeepConnectionDeadline() = runBlocking {
        MockWebServer().use { server ->
            val deadlines = CopyOnWriteArrayList<List<Long>>()
            val http = OkHttpClient.Builder().addInterceptor { chain ->
                deadlines.add(listOf(chain.connectTimeoutMillis().toLong(), chain.readTimeoutMillis().toLong(),
                    chain.writeTimeoutMillis().toLong(), chain.call().timeout().timeoutNanos()))
                chain.proceed(chain.request())
            }.build()
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "DEVICE", 5, http)
            for ((method, path) in listOf("GET" to "/api/media/upload-limits", "GET" to "/api/media/uploads/saved",
                "POST" to "/api/media/uploads", "PUT" to "/api/media/uploads/saved/ranges?offset=0",
                "POST" to "/api/media/uploads/saved/complete")) {
                server.enqueue(MockResponse().setBody("{}"))
                api.request(method, path, waitForUpload = true)
            }
            assertEquals(List(5) { listOf(10_000L, 0L, 0L, 0L) }, deadlines)
            server.enqueue(MockResponse().setBody("{}"))
            api.request("GET", "/api/dashboard")
            assertEquals(listOf(10_000L, 10_000L, 10_000L, 30_000_000_000L), deadlines.last())
        }
    }

    @Test fun transportFailuresRetainSafeDistinctReasonsWithoutReplayingUpload() = runBlocking {
        for ((exception, expected) in listOf(
            java.net.SocketTimeoutException("SECRET") to "TIMEOUT",
            java.io.InterruptedIOException("SECRET") to "TIMEOUT",
            java.net.UnknownHostException("SECRET") to "DNS",
            javax.net.ssl.SSLHandshakeException("SECRET") to "TLS",
            java.net.ConnectException("SECRET") to "CONNECTION",
            java.net.ProtocolException("SECRET") to "INVALID_RESPONSE",
        )) {
            val attempts = AtomicInteger()
            val http = OkHttpClient.Builder().addInterceptor { attempts.incrementAndGet(); throw exception }.build()
            val api = DojoApi("https://example.test", "SECRET", 5, http)
            val failure = runCatching { api.request("POST", "/api/media/uploads") }.exceptionOrNull() as ApiFailure
            assertEquals(expected, failure.transportIssue?.name)
            assertFalse(failure.toString().contains("SECRET"))
            assertNull(failure.cause)
            assertEquals(1, attempts.get())
        }
    }
    @Test fun backgroundUploadReadsAndConflictActionsHaveFiniteDeadlines() = runBlocking {
        MockWebServer().use { server ->
            val deadlines = CopyOnWriteArrayList<List<Long>>()
            val http = OkHttpClient.Builder().addInterceptor { chain ->
                deadlines.add(listOf(chain.readTimeoutMillis().toLong(), chain.writeTimeoutMillis().toLong(),
                    chain.call().timeout().timeoutNanos()))
                chain.proceed(chain.request())
            }.build()
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "DEVICE", 5, http)
            server.enqueue(MockResponse().setBody(upload))
            api.uploadStatus("saved")
            assertEquals(listOf(10_000L, 10_000L, 30_000_000_000L), deadlines.last())
            server.enqueue(MockResponse().setBody(upload))
            api.resolveUpload("saved", ResolveConflictIn(decision = "keep_both"))
            assertEquals(listOf(60_000L, 60_000L, 180_000_000_000L), deadlines.last())
        }
    }

    @Test fun cancellingIndefiniteUploadResponseCancelsCallWithoutReplaying() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
            val cancelled = CompletableDeferred<Unit>()
            val http = OkHttpClient.Builder().eventListener(object : okhttp3.EventListener() {
                override fun canceled(call: okhttp3.Call) { cancelled.complete(Unit) }
            }).build()
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "DEVICE", 5, http)
            val pending = async { api.request("POST", "/api/media/uploads", waitForUpload = true) }
            withContext(Dispatchers.IO) { server.takeRequest() }
            pending.cancelAndJoin()
            withTimeout(3000) { cancelled.await() }
            assertTrue(pending.isCancelled)
            assertEquals(1, server.requestCount)
        }
    }

    @Test fun safeReadRecoversFromTwoTransportTimeoutsWithoutUserRetry() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody("""{"id":1,"kind":"device","name":"test","created_at":"now","created_by":"test","last_seen_at":null,"revoked_at":null}"""))
            val attempts = AtomicInteger()
            val http = OkHttpClient.Builder().addInterceptor { chain ->
                if (attempts.incrementAndGet() <= 2) throw java.net.SocketTimeoutException("Synthetic timeout")
                chain.proceed(chain.request())
            }.build()
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "DEVICE", 5, http)
            assertEquals(1, api.me().id)
            assertEquals(3, attempts.get())
            assertEquals(1, server.requestCount)
        }
    }

    @Test fun safeReadTransportRetriesAreBounded() = runBlocking {
        val attempts = AtomicInteger()
        val http = OkHttpClient.Builder().addInterceptor {
            attempts.incrementAndGet()
            throw java.net.SocketTimeoutException("Synthetic timeout")
        }.build()
        val api = DojoApi("https://example.test", "DEVICE", 5, http)
        assertEquals(0, (runCatching { api.me() }.exceptionOrNull() as ApiFailure).status)
        assertEquals(3, attempts.get())
    }

    @Test fun safeReadDoesNotRetryHttpRejection() = runBlocking {
        for (status in listOf(401, 426, 429, 503)) MockWebServer().use { server ->
            server.enqueue(MockResponse().setResponseCode(status))
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "DEVICE", 5, OkHttpClient())
            assertEquals(status, (runCatching { api.me() }.exceptionOrNull() as ApiFailure).status)
            assertEquals(1, server.requestCount)
        }
    }

    @Test fun cancellingSafeReadStopsTransportRetries() = runBlocking {
        val failed = CompletableDeferred<Unit>()
        val attempts = AtomicInteger()
        val http = OkHttpClient.Builder().addInterceptor {
            attempts.incrementAndGet()
            throw java.net.SocketTimeoutException("Synthetic timeout")
        }.build()
        val api = DojoApi("https://example.test", "DEVICE", 5, http) { trace ->
            if (trace.contains("stage=failed")) failed.complete(Unit)
        }
        val pending = async { api.me() }
        failed.await()
        pending.cancelAndJoin()
        assertEquals(1, attempts.get())
    }

    @Test fun slowUploadResponseSurvivesOrdinaryReadDeadline() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody(upload).setHeadersDelay(11, TimeUnit.SECONDS))
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "DEVICE", 5, OkHttpClient())
            assertEquals("saved", api.uploadRange("saved", 0, "a".repeat(64), byteArrayOf(7)).uploadId)
            assertEquals(1, server.requestCount)
        }
    }

    @Test fun getRecoversWhenReusedConnectionClosesBeforeResponse() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody("{}"))
            server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST))
            server.enqueue(MockResponse().setBody("""{"recovered":true}"""))
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "DEVICE", 5, OkHttpClient())
            api.request("GET", "/api/test")
            assertEquals(buildJsonObject { put("recovered", true) }, api.request("GET", "/api/test"))
            val requests = List(3) { server.takeRequest() }
            assertEquals(listOf(0, 1, 0), requests.map { it.sequenceNumber })
            assertTrue(requests.all { it.method == "GET" && it.getHeader("Authorization") == "Bearer DEVICE" })
        }
    }

    @Test fun mutationsNeverReplayWhenReusedConnectionClosesBeforeResponse() = runBlocking {
        for (method in listOf("POST", "PUT", "PATCH", "DELETE")) {
            MockWebServer().use { server ->
                server.enqueue(MockResponse().setBody("{}"))
                server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST))
                server.enqueue(MockResponse().setBody("{}"))
                val api = DojoApi(server.url("/").toString().trimEnd('/'), "DEVICE", 5, OkHttpClient())
                api.request("GET", "/api/test")
                assertEquals(method, 0, (runCatching { api.request(method, "/api/test") }.exceptionOrNull() as ApiFailure).status)
                assertEquals(method, 2, server.requestCount)
                assertEquals("GET", server.takeRequest().method)
                assertEquals(method, server.takeRequest().method)
            }
        }
    }

    @Test fun diagnosticsRedactCredentialsQueriesAndDynamicPaths() = runBlocking {
        MockWebServer().use { server ->
            val logs = CopyOnWriteArrayList<String>()
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "DEVICE-SECRET", 5, OkHttpClient(), logs::add)
            server.enqueue(MockResponse().setResponseCode(503).setBody("""{"detail":"RESPONSE-SECRET"}"""))
            val failure = runCatching {
                api.request("POST", "/api/media/uploads/UPLOAD-SECRET/resolve?token=QUERY-SECRET",
                    buildJsonObject { put("token", "BODY-SECRET") })
            }.exceptionOrNull() as ApiFailure
            assertEquals(503, failure.status)
            assertTrue(logs.any { it.contains("POST /api/media/uploads/:id/resolve") })
            assertTrue(logs.any { it.contains("stage=headers") && it.contains("status=503") })
            assertTrue(logs.any { it.contains("stage=failed") && it.contains("error=ApiFailure") })
            assertTrue(logs.all { it.contains("id=") && it.contains("elapsed_ms=") })
            for (secret in listOf("DEVICE-SECRET", "RESPONSE-SECRET", "UPLOAD-SECRET", "QUERY-SECRET", "BODY-SECRET")) {
                assertFalse("Diagnostic leaked $secret", logs.any { it.contains(secret) })
            }
            assertEquals(1, server.requestCount)
        }
    }

    @Test fun diagnosticsIdentifyTransportFailureWithoutMessageOrReplay() = runBlocking {
        val logs = CopyOnWriteArrayList<String>()
        val attempts = AtomicInteger()
        val http = OkHttpClient.Builder().addInterceptor {
            attempts.incrementAndGet()
            throw java.net.SocketTimeoutException("TRANSPORT-SECRET")
        }.build()
        val api = DojoApi("https://example.test", "DEVICE-SECRET", 5, http, logs::add)
        assertEquals(0, (runCatching { api.request("POST", "/api/test") }.exceptionOrNull() as ApiFailure).status)
        assertTrue(logs.any { it.contains("stage=failed") && it.contains("error=SocketTimeoutException") })
        assertFalse(logs.any { it.contains("TRANSPORT-SECRET") || it.contains("DEVICE-SECRET") })
        assertEquals(1, attempts.get())
    }

    @Test fun diagnosticSinkFailureCannotBreakSuccessfulRequest() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody("{}"))
            val attempts = AtomicInteger()
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "DEVICE", 5, OkHttpClient()) {
                attempts.incrementAndGet()
                throw IOException("Diagnostic sink unavailable")
            }
            assertEquals(buildJsonObject {}, api.request("GET", "/api/test"))
            assertTrue(attempts.get() >= 3)
            assertEquals(1, server.requestCount)
        }
    }

    @Test fun activityUsesAuthenticatedLatest50AndBothActorShapes() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody("""{"events":[{"id":2,"action":"package.created","occurred_at":"2026-10-12T12:00:00Z","details":{},"actor":{"id":1,"name":"Telefon","kind":"device"}},{"id":1,"action":"worker.started","occurred_at":"2026-10-12T11:00:00Z","details":{},"actor":"system"}],"next_cursor":null}"""))
            val page = DojoApi(server.url("/").toString().trimEnd('/'), "SYNTHETIC", 5, OkHttpClient()).activity()
            assertEquals(2, page.events.size)
            assertNull(page.nextCursor)
            assertEquals("Telefon", page.events.first().actor.jsonObject["name"]!!.jsonPrimitive.content)
            assertEquals(JsonPrimitive("system"), page.events.last().actor)
            val request = server.takeRequest()
            assertEquals("/api/activity?limit=50", request.path)
            assertEquals("Bearer SYNTHETIC", request.getHeader("Authorization"))
            assertEquals("5", request.getHeader("X-Android-Version-Code"))
        }
    }
    @Test fun reviewPreviewIsAuthenticatedBoundedAndNeverFollowsRedirects() = runBlocking {
        MockWebServer().use { server ->
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "DEVICE", 1, OkHttpClient())
            val directory = Files.createTempDirectory("review-preview").toFile()
            val file = directory.resolve("exact.mp4")
            val path = "/api/packages/active/render/preview?expected_folder_name=active&revision=exact"
            try {
                server.enqueue(MockResponse().setBody("preview"))
                api.downloadReviewPreview(path, file, 10)
                assertEquals("preview", file.readText())
                val request = server.takeRequest()
                assertEquals("Bearer DEVICE", request.getHeader("Authorization"))
                assertEquals("1", request.getHeader("X-Android-Version-Code"))
                assertEquals(path, request.path)
                server.enqueue(MockResponse().setBody("too large"))
                assertEquals(413, (runCatching { api.downloadReviewPreview(path, file, 2) }.exceptionOrNull() as ApiFailure).status)
                assertFalse(file.exists())
                server.enqueue(MockResponse().setResponseCode(302).setHeader("Location", "https://evil.example/"))
                assertEquals(302, (runCatching { api.downloadReviewPreview(path, file, 10) }.exceptionOrNull() as ApiFailure).status)
                assertFalse(file.exists())
                assertEquals(3, server.requestCount)
            } finally { directory.deleteRecursively() }
        }
    }

    @Test fun cancelledReviewTransferRemovesItsPartialFile() = runBlocking {
        MockWebServer().use { server ->
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "DEVICE", 1, OkHttpClient())
            val file = Files.createTempFile("review-cancel", ".mp4").toFile()
            try {
                server.enqueue(MockResponse().setBody("preview").setBodyDelay(2, TimeUnit.SECONDS))
                val pending = async { api.downloadReviewPreview("/api/packages/active/render/preview?revision=exact", file, 10) }
                withContext(Dispatchers.IO) { server.takeRequest() }
                pending.cancelAndJoin()
                withTimeout(3000) { while (file.exists()) delay(10) }
                assertEquals(1, server.requestCount)
            } finally { file.delete() }
        }
    }

    @Test fun cacheWriteFailureDoesNotDeleteParentOrSiblingFiles() = runBlocking {
        MockWebServer().use { server ->
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "DEVICE", 1, OkHttpClient())
            val parent = Files.createTempFile("review-no-directory", ".owned").toFile()
            val destination = parent.resolve("preview.mp4")
            try {
                server.enqueue(MockResponse().setBody("preview"))
                assertEquals(0, (runCatching { api.downloadReviewPreview("/api/packages/active/render/preview?revision=exact", destination, 10) }.exceptionOrNull() as ApiFailure).status)
                assertFalse(destination.exists())
                assertTrue(parent.exists())
            } finally { parent.delete() }
        }
    }
    @Test fun reviewActionsUseDisplayedIdentityAndExplicitBodies() = runBlocking {
        MockWebServer().use { server ->
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "DEVICE", 1, OkHttpClient())
            repeat(3) { server.enqueue(MockResponse().setBody("{}")) }
            api.approveReview(7, 3)
            api.skipReview(7, 3)
            api.rescheduleReview(7, 3, "2099-10-11T10:00:00+03:00")
            val approve = server.takeRequest()
            assertEquals("/api/reviews/7/approve", approve.path)
            assertEquals("POST", approve.method)
            assertEquals("{\"version\":3}", approve.body.readUtf8())
            assertEquals("Bearer DEVICE", approve.getHeader("Authorization"))
            assertEquals("1", approve.getHeader("X-Android-Version-Code"))
            val skip = server.takeRequest()
            assertEquals("/api/reviews/7/skip", skip.path)
            assertEquals(Json.parseToJsonElement("""{"version":3,"confirmed":true}"""), Json.parseToJsonElement(skip.body.readUtf8()))
            val reschedule = server.takeRequest()
            assertEquals("/api/reviews/7/reschedule", reschedule.path)
            assertEquals("2099-10-11T10:00:00+03:00", Json.parseToJsonElement(reschedule.body.readUtf8()).jsonObject["new_due_at"]!!.jsonPrimitive.content)
        }
    }

    @Test fun emptyActionsRenderAndPushUseExistingTypedContracts() = runBlocking {
        MockWebServer().use { server ->
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "DEVICE", 1, OkHttpClient())
            val result = """{"occurrence_id":2,"package_folder":"active","status":"skipped","next_regular_at":null,"oneoff_occurrence_id":null,"new_due_at":null}"""
            server.enqueue(MockResponse().setBody(result))
            assertEquals(2, api.skipEmptyOccurrence(2, EmptySkipIn(expectedFolderName = "active", confirmed = true)).occurrenceId)
            assertEquals("/api/reviews/occurrences/2/skip", server.takeRequest().path)
            server.enqueue(MockResponse().setBody(result.replace("skipped", "rescheduled")))
            api.rescheduleEmptyOccurrence(2, EmptyRescheduleIn("active", "2099-10-11T10:00:00+03:00"))
            val reschedule = server.takeRequest()
            assertEquals("/api/reviews/occurrences/2/reschedule", reschedule.path)
            assertEquals("active", Json.parseToJsonElement(reschedule.body.readUtf8()).jsonObject["expected_folder_name"]!!.jsonPrimitive.content)
            server.enqueue(MockResponse().setBody("""{"render_revision":"exact","stale":true}"""))
            assertEquals("exact", api.renderPackage("active").renderRevision)
            val render = server.takeRequest()
            assertEquals("/api/packages/active/render", render.path)
            assertEquals("active", Json.parseToJsonElement(render.body.readUtf8()).jsonObject["expected_folder_name"]!!.jsonPrimitive.content)
            repeat(2) { server.enqueue(MockResponse().setBody("{}")) }
            api.registerPushToken("SYNTHETIC_FCM")
            api.removePushToken()
            val put = server.takeRequest()
            assertEquals("PUT", put.method)
            assertEquals("/api/pairing/me/push-token", put.path)
            assertEquals("{\"token\":\"SYNTHETIC_FCM\"}", put.body.readUtf8())
            assertEquals("DELETE", server.takeRequest().method)
        }
    }

    @Test fun reviewReadKeepsExactCaptionAndRejectsMalformedActionResponse() = runBlocking {
        MockWebServer().use { server ->
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "DEVICE", 1, OkHttpClient())
            server.enqueue(MockResponse().setBody("""{"next_regular_at":null,"preview_url":null,"render_ready":false,"review":{"caption":"Exact caption\n#dojo","created_at":"2026-10-11T10:00:00+03:00","id":7,"occurrence_id":2,"package_folder":"active","revision_digest":"exact","status":"pending","version":3}}"""))
            assertEquals("Exact caption\n#dojo", api.review(7).review.caption)
            assertEquals("/api/reviews/7", server.takeRequest().path)
            server.enqueue(MockResponse().setBody("[]"))
            assertTrue(runCatching { api.approveReview(7, 3) }.exceptionOrNull() is SerializationException)
            assertEquals(2, server.requestCount)
        }
    }

    @Test fun mediaMutationsEncodeIdentityAndNeverUseUnguardedLegacyTrims() = runBlocking {
        MockWebServer().use { server ->
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "SYNTHETIC", 5, OkHttpClient())
            repeat(3) { server.enqueue(MockResponse().setBody("{}")) }
            api.removeMedia("folder +/", "id/+?")
            api.restoreMedia("folder +/", "id/+?")
            api.selectVideoRanges("folder +/", mapOf("id/+?" to listOf(VideoRangeOut(start = 1.0, end = 2.0))))
            val remove = server.takeRequest()
            assertEquals("/api/packages/active/media/id%2F%2B%3F/remove", remove.requestUrl!!.encodedPath)
            assertEquals("folder +/", remove.requestUrl!!.queryParameter("expected_folder_name"))
            assertEquals("Bearer SYNTHETIC", remove.getHeader("Authorization"))
            assertEquals("5", remove.getHeader("X-Android-Version-Code"))
            assertEquals("/api/packages/active/media/id%2F%2B%3F/restore", server.takeRequest().requestUrl!!.encodedPath)
            val selections = server.takeRequest()
            assertEquals("/api/packages/active/selections", selections.path)
            assertEquals(Json.parseToJsonElement("""{"expected_folder_name":"folder +/","selections":{"id/+?":[{"start":1.0,"end":2.0}]}}"""), Json.parseToJsonElement(selections.body.readUtf8()))
        }
    }
    @Test fun skippedUploadLookupPaginatesAuditAndDoesNotGuessFromOtherUploads() = runBlocking {
        MockWebServer().use { server ->
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "SYNTHETIC", 5, OkHttpClient())
            server.enqueue(MockResponse().setBody("""{"events":[{"action":"conflict.resolved","details":{"upload_id":"other","decision":"keep_target"}}],"next_cursor":10}"""))
            server.enqueue(MockResponse().setBody("""{"events":[{"action":"conflict.resolved","details":{"upload_id":"saved","decision":"keep_target"}}],"next_cursor":null}"""))
            assertTrue(api.uploadWasSkipped("saved"))
            assertEquals("/api/activity?limit=100", server.takeRequest().path)
            val second = server.takeRequest()
            assertEquals("/api/activity?limit=100&before_id=10", second.path)
            assertEquals("Bearer SYNTHETIC", second.getHeader("Authorization"))
            server.enqueue(MockResponse().setBody("""{"events":[{"action":"upload.expired","details":{"upload_id":"expired"}}],"next_cursor":null}"""))
            assertFalse(api.uploadWasSkipped("expired"))
            server.enqueue(MockResponse().setBody("""{"events":[],"next_cursor":null}"""))
            assertEquals(0, (runCatching { api.uploadWasSkipped("saved") }.exceptionOrNull() as ApiFailure).status)
            server.enqueue(MockResponse().setBody("""{"events":[],"next_cursor":10}"""))
            server.enqueue(MockResponse().setBody("""{"events":[],"next_cursor":10}"""))
            assertTrue(runCatching { api.uploadWasSkipped("saved") }.exceptionOrNull() is SerializationException)
        }
    }
    @Test fun conflictResolutionAndPreviewUseAuthenticatedEncodedPaths() = runBlocking {
        MockWebServer().use { server ->
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "SYNTHETIC", 5, OkHttpClient())
            server.enqueue(MockResponse().setBody(upload))
            api.resolveUpload("id /ğ", ResolveConflictIn(decision = "keep_selected", targetMediaId = "target", applyToAll = true, confirmedOverwrite = true))
            val resolve = server.takeRequest()
            assertEquals("/api/media/uploads/id%20%2F%C4%9F/resolve", resolve.path)
            val body = Json.parseToJsonElement(resolve.body.readUtf8()).jsonObject
            assertTrue(body["confirmed_overwrite"]!!.jsonPrimitive.boolean)
            assertTrue(body["apply_to_all"]!!.jsonPrimitive.boolean)
            assertEquals("keep_selected", body["decision"]!!.jsonPrimitive.content)
            val file = Files.createTempFile("preview", ".jpg").toFile()
            try {
                server.enqueue(MockResponse().setBody("preview"))
                api.conflictPreview("id /ğ", "target /ğ", file, 10)
                assertEquals("preview", file.readText())
                val request = server.takeRequest()
                assertEquals("/api/media/uploads/id%20%2F%C4%9F/conflicts/target%20%2F%C4%9F/preview", request.path)
                assertEquals("Bearer SYNTHETIC", request.getHeader("Authorization"))
                assertEquals("5", request.getHeader("X-Android-Version-Code"))
                server.enqueue(MockResponse().setBody("too large"))
                assertEquals(413, (runCatching { api.conflictPreview("saved", "target", file, 2) }.exceptionOrNull() as ApiFailure).status)
                assertFalse(file.exists())
                server.enqueue(MockResponse().setResponseCode(302).setHeader("Location", "https://evil.example/"))
                assertEquals(302, (runCatching { api.conflictPreview("saved", "target", file, 10) }.exceptionOrNull() as ApiFailure).status)
                assertFalse(file.exists())
            } finally { file.delete() }
        }
    }
    @Test fun cancelledPreviewRemovesPartialFileWithoutRetry() = runBlocking {
        MockWebServer().use { server ->
            val file = Files.createTempFile("preview-cancel", ".mp4").toFile()
            try {
                val api = DojoApi(server.url("/").toString().trimEnd('/'), "SYNTHETIC", 5, OkHttpClient())
                server.enqueue(MockResponse().setBody("preview").setBodyDelay(2, TimeUnit.SECONDS))
                val pending = async { api.conflictPreview("saved", "target", file, 10) }
                withContext(Dispatchers.IO) { server.takeRequest() }
                pending.cancelAndJoin()
                withTimeout(3000) { while (file.exists()) delay(10) }
                assertEquals(1, server.requestCount)
            } finally { file.delete() }
        }
    }
    private val upload = """{"upload_id":"saved","declared_size_bytes":2147483648,"received_bytes":2147483648,"received_ranges":[[0,2147483648]],"status":"receiving","conflicts":[{"media_id":"target","size_bytes":3,"preview":{"ready":true}}]}"""
    @Test fun uploadMethodsPreserveLargeOffsetsAndCancellation() = runBlocking {
        MockWebServer().use { server ->
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "SYNTHETIC", 5, OkHttpClient())
            server.enqueue(MockResponse().setBody("""{"max_file_bytes":2147483648,"max_package_bytes":21474836480,"active_package_id":0}"""))
            assertEquals(2147483648L, api.uploadLimits().maxFileBytes)
            assertEquals("/api/media/upload-limits", server.takeRequest().path)
            server.enqueue(MockResponse().setBody(upload))
            val status = api.uploadStatus("saved")
            assertEquals(2147483648L, status.receivedBytes)
            assertEquals(listOf(listOf(0L, 2147483648L)), status.receivedRanges)
            assertEquals("target", status.conflicts.single()["media_id"]!!.jsonPrimitive.content)
            server.takeRequest()
            server.enqueue(MockResponse().setBody(upload))
            api.uploadRange("saved", 2147483648L, "a".repeat(64), byteArrayOf(7))
            val put = server.takeRequest()
            assertEquals("PUT", put.method)
            assertEquals("2147483648", put.requestUrl!!.queryParameter("offset"))
            assertEquals("a".repeat(64), put.requestUrl!!.queryParameter("checksum_sha256"))
            assertEquals("Bearer SYNTHETIC", put.getHeader("Authorization"))
            assertEquals("5", put.getHeader("X-Android-Version-Code"))
            assertArrayEquals(byteArrayOf(7), put.body.readByteArray())
            server.enqueue(MockResponse().setBody(upload).setBodyDelay(2, TimeUnit.SECONDS))
            val pending = async { api.uploadRange("saved", 0, "a".repeat(64), byteArrayOf(1)) }
            withContext(Dispatchers.IO) { server.takeRequest() }
            pending.cancelAndJoin()
            assertEquals(4, server.requestCount)
        }
    }
    @Test fun uploadErrorsStaySecretFree() = runBlocking {
        MockWebServer().use { server ->
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "SYNTHETIC", 5, OkHttpClient())
            server.enqueue(MockResponse().setResponseCode(409).setBody("""{"detail":"package limit exceeded"}"""))
            val error = runCatching { api.uploadStatus("saved") }.exceptionOrNull() as ApiFailure
            assertEquals("package limit exceeded", error.detail)
            assertFalse(error.toString().contains("package limit"))
            server.enqueue(MockResponse().setResponseCode(302).setHeader("Location", "https://evil.example/"))
            assertEquals(302, (runCatching { api.completeUpload("saved") }.exceptionOrNull() as ApiFailure).status)
            server.enqueue(MockResponse().setBody("{}"))
            assertTrue(runCatching { api.uploadStatus("saved") }.exceptionOrNull() is SerializationException)
        }
    }
    @Test fun headersPatchAndSecretFreeErrors() = runBlocking {
        MockWebServer().use { server ->
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "DEVICE-SECRET", 7, OkHttpClient())
            server.enqueue(MockResponse().setBody("{}"))
            api.request("PATCH", "/api/settings/branding", buildJsonObject { put("caption_template", "Merhaba") })
            val request = server.takeRequest()
            assertEquals("Bearer DEVICE-SECRET", request.getHeader("Authorization"))
            assertEquals("7", request.getHeader("X-Android-Version-Code"))
            assertEquals("""{"caption_template":"Merhaba"}""", request.body.readUtf8())
            server.enqueue(MockResponse().setBody("{}"))
            api.request("PATCH", "/api/settings/branding", buildJsonObject { put("intro_asset", JsonNull); put("intro_duration", JsonNull) })
            assertEquals("""{"intro_asset":null,"intro_duration":null}""", server.takeRequest().body.readUtf8())
            server.enqueue(MockResponse().setBody("{\"client_id\":1,\"kind\":\"device\",\"token\":\"new\"}"))
            api.pair("12345678", "Telefon")
            assertNull(server.takeRequest().getHeader("Authorization"))
            server.enqueue(MockResponse().setResponseCode(422).setBody("{\"detail\":\"DEVICE-SECRET\"}"))
            val error = runCatching { api.request("POST", "/api/test") }.exceptionOrNull()!!
            assertTrue(error is ApiFailure)
            assertFalse(error.toString().contains("DEVICE-SECRET"))
        }
    }

    @Test fun redirectsMalformedResponsesAndCrossOriginPreviewsFail() = runBlocking {
        MockWebServer().use { server ->
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "secret", 1, OkHttpClient())
            server.enqueue(MockResponse().setResponseCode(302).setHeader("Location", "https://evil.example/"))
            assertEquals(302, (runCatching { api.request("POST", "/api/test") }.exceptionOrNull() as ApiFailure).status)
            server.enqueue(MockResponse().setBody("{}"))
            assertTrue(runCatching { api.dashboard() }.exceptionOrNull() is SerializationException)
            assertTrue(runCatching { api.preview("https://evil.example/image") }.isFailure)
            server.enqueue(MockResponse().setBody("image"))
            assertEquals("image", api.preview("/api/settings/branding/assets/test").toString(Charsets.UTF_8))
            repeat(2) { server.takeRequest() }
            assertEquals("Bearer secret", server.takeRequest().getHeader("Authorization"))
        }
    }

    @Test fun cancellationDoesNotRetryMutation() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody("{}").setBodyDelay(2, TimeUnit.SECONDS))
            val api = DojoApi(server.url("/").toString().trimEnd('/'), "secret", 1, OkHttpClient())
            val job = async { api.request("POST", "/api/test") }
            withContext(Dispatchers.IO) { server.takeRequest() }
            job.cancel()
            assertTrue(runCatching { job.await() }.exceptionOrNull() is CancellationException)
            assertEquals(1, server.requestCount)
        }
    }
}
