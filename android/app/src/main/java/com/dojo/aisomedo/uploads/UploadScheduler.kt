package com.dojo.aisomedo.uploads

import android.app.job.JobInfo
import android.app.job.JobScheduler
import android.content.ComponentName
import android.content.Context
import android.os.Build
import android.os.PersistableBundle
import androidx.work.*
import java.util.concurrent.TimeUnit

enum class SchedulerKind { UIDT, WORK_MANAGER }
fun schedulerKind(apiLevel: Int) = if (apiLevel >= 34) SchedulerKind.UIDT else SchedulerKind.WORK_MANAGER

class UploadScheduler(private val context: Context) {
    fun schedule(bindingId: String): Boolean = try {
        require(bindingId.matches(Regex("[a-f0-9]{64}")))
        if (Build.VERSION.SDK_INT >= 34) {
            val extras = PersistableBundle().apply { putString("binding", bindingId) }
            val job = JobInfo.Builder(3300, ComponentName(context, UploadJobService::class.java))
                .setUserInitiated(true).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setEstimatedNetworkBytes(JobInfo.NETWORK_BYTES_UNKNOWN.toLong(), JobInfo.NETWORK_BYTES_UNKNOWN.toLong())
                .setBackoffCriteria(30_000, JobInfo.BACKOFF_POLICY_EXPONENTIAL).setExtras(extras).build()
            context.getSystemService(JobScheduler::class.java).forNamespace("dojo-uploads").schedule(job) == JobScheduler.RESULT_SUCCESS
        } else {
            val manager = WorkManager.getInstance(context)
            // Explicit user actions wake the queue, even if a previous runner is finishing.
            manager.cancelUniqueWork("dojo-upload-$bindingId").result.get()
            val work = OneTimeWorkRequestBuilder<UploadWorker>()
                .setInputData(workDataOf("binding" to bindingId))
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS).build()
            manager.enqueueUniqueWork("dojo-upload-$bindingId", ExistingWorkPolicy.KEEP, work).result.get()
            true
        }
    } catch (_: Exception) { false }

    fun cancel(bindingId: String) {
        if (Build.VERSION.SDK_INT >= 34) {
            val manager = context.getSystemService(JobScheduler::class.java).forNamespace("dojo-uploads")
            if (manager.getPendingJob(3300)?.extras?.getString("binding") == bindingId) manager.cancel(3300)
        } else WorkManager.getInstance(context).cancelUniqueWork("dojo-upload-$bindingId").result.get()
    }
}
