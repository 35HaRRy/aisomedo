package com.dojo.aisomedo.uploads

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream

class UploadSourceTest {
    @Test fun preparationIsBoundedAndChecksActualLength() = runBlocking {
        val bytes = ByteArray(CHUNK_BYTES + 1) { (it % 251).toByte() }
        val identity = prepareFile({ bytes.inputStream() }, null, 2L * CHUNK_BYTES) {}
        assertEquals(2097153L, identity.size)
        assertEquals(2, identity.chunkHashes.size)
        val short = prepareFile({ object : ByteArrayInputStream(bytes) {
            override fun read(b: ByteArray, off: Int, len: Int) = super.read(b, off, minOf(len, 13))
        } }, bytes.size.toLong(), 2L * CHUNK_BYTES) {}
        assertEquals(identity, short)
        for ((input, declared, max, issue) in listOf(
            listOf(byteArrayOf(), null, 10L, UploadIssue.OVERSIZE),
            listOf(ByteArray(11), null, 10L, UploadIssue.OVERSIZE),
            listOf(ByteArray(2), 1L, 10L, UploadIssue.WRONG_FILE),
        )) {
            val error = runCatching { prepareFile({ (input as ByteArray).inputStream() }, declared as Long?, max as Long) {} }.exceptionOrNull()
            assertEquals(issue, (error as UploadFailure).issue)
        }
    }
    @Test fun changedBytesFailVerification() = runBlocking {
        val expected = prepareFile({ byteArrayOf(1, 2).inputStream() }, 2, 10) {}
        assertEquals(UploadIssue.WRONG_FILE, (runCatching {
            verifyFile({ byteArrayOf(2, 1).inputStream() }, expected) {}
        }.exceptionOrNull() as UploadFailure).issue)
    }
    @Test fun cancellationClosesSource() = runBlocking {
        var closed = false
        val pending = async {
            prepareFile({ object : ByteArrayInputStream(ByteArray(CHUNK_BYTES * 2)) {
                override fun close() { closed = true; super.close() }
            } }, null, 3L * CHUNK_BYTES) { throw CancellationException() }
        }
        assertTrue(runCatching { pending.await() }.exceptionOrNull() is CancellationException)
        assertTrue(closed)
    }
}
