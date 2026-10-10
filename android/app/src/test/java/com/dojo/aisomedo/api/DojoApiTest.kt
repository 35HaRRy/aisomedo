package com.dojo.aisomedo.api

import kotlinx.coroutines.*
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.*
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.TimeUnit
import java.nio.file.Files

class DojoApiTest {
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
