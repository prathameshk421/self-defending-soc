# Endpoint ingest goldens

Contract fixtures for `lab-endpoint` RawRecord wrapping. They are not proof a guest ran.

IdP `auth.log` is application identity. Host `syslog.log` `identifier=sshd|sudo` is host OS auth.

Do not overwrite these from live QEMU output.

Payload `source=auditd` is a channel tag, not kernel proof. Payload `source=nft` / `source=dns` is likewise untrusted self-report.
