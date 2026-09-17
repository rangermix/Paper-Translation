# M2 lifecycle retention

The executable policy and Compose commands are documented in [retention.md](retention.md). M2 adds explicit independent translation memory and immutable source/editorial history; the maintenance retention sweep does not remove either. All registered export directories, including incomplete-draft export snapshots, remain protected while their Export record exists.

Keep document tombstoning, current-publication pointer changes, explicit memory deletion, offline exports and whole-instance backup retention distinct. Removing an online document cannot recall a downloaded copy. Backups have an explicit 30-day local expiry; the maintenance lock covers both backup and cleanup to prevent deleting files while they are copied.
