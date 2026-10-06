package com.dojo.aisomedo.onboarding

import com.dojo.aisomedo.api.ApiFailure
import java.io.InputStream
import org.junit.Assert.*
import org.junit.Test

class BrandingReadTest {
    private class Synthetic(private val size: Int) : InputStream() {
        var count = 0
        var closed = false
        override fun read(): Int = if (count++ < size) 1 else -1
        override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
            val available = minOf(length, size - count)
            if (available == 0) return -1
            count += available; return available
        }
        override fun close() { closed = true }
    }
    @Test fun exactLimitAllowedAndUnknownSizeStopsAtLimitPlusOne() {
        val limit = 10 * 1024 * 1024
        val valid = Synthetic(limit)
        assertEquals(limit, valid.use { readBrandingImage(it) }.size)
        assertTrue(valid.closed)
        val oversized = Synthetic(limit + 10000)
        assertThrows(ApiFailure::class.java) { oversized.use { readBrandingImage(it) } }
        assertEquals(limit + 1, oversized.count)
        assertTrue(oversized.closed)
    }
}
