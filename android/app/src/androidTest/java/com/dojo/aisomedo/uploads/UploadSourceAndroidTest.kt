package com.dojo.aisomedo.uploads

import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class UploadSourceAndroidTest {
    @Test fun retainedGrantSurvivesRecreatedSource() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val target = instrumentation.targetContext
        val test = instrumentation.context
        val uri = DocumentsContract.buildDocumentUri("com.dojo.aisomedo.test.documents", "unknown_source")
        val file = File(test.cacheDir, "upload-test-unknown_source").apply { writeBytes(byteArrayOf(1, 2, 3)) }
        test.grantUriPermission(target.packageName, uri, Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
        try {
            val document = UploadSource(target.contentResolver).retain(uri)
            assertNull(document.size)
            assertArrayEquals(byteArrayOf(1, 2, 3), UploadSource(target.contentResolver).open(document.uri).use { it.readBytes() })
            assertTrue(target.contentResolver.persistedUriPermissions.any { it.uri == uri && it.isReadPermission })
            UploadSource(target.contentResolver).release(document.uri)
        } finally {
            test.revokeUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
            file.delete()
        }
    }
    @Test fun missingGrantHasRecoverableIssue() {
        val source = UploadSource(InstrumentationRegistry.getInstrumentation().targetContext.contentResolver)
        assertEquals(UploadIssue.FILE_ACCESS, (runCatching { source.retain(Uri.parse("content://com.dojo.aisomedo.test.documents/document/missing")) }.exceptionOrNull() as UploadFailure).issue)
    }
}
