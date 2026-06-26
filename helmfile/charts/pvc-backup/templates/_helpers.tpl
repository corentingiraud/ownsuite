{{/*
rclone remote configuration as env vars, shared by the backup CronJobs and the restore
Jobs (ADR-032). Two remotes:
  - offsite       : the off-site backup store (S3-compatible)
  - offsitecrypt  : a crypt overlay on offsite:<bucket>/<pvcPrefix> for client-side
                    encryption (ADR-017). Its password is obscured at runtime from
                    OWNSUITE_CRYPT_PASSPHRASE (rclone wants an obscured value).
The source/destination on the PVC side is a mounted local path (/data), not a remote.
*/}}
{{- define "pvc-backup.env" -}}
- name: RCLONE_CONFIG_OFFSITE_TYPE
  value: s3
- name: RCLONE_CONFIG_OFFSITE_PROVIDER
  value: Other
- name: RCLONE_CONFIG_OFFSITE_ENDPOINT
  value: {{ .Values.offsite.endpoint | quote }}
- name: RCLONE_CONFIG_OFFSITE_REGION
  value: {{ .Values.offsite.region | quote }}
- name: RCLONE_CONFIG_OFFSITE_FORCE_PATH_STYLE
  value: "true"
- name: RCLONE_CONFIG_OFFSITE_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef:
      name: {{ .Values.offsite.secret | quote }}
      key: {{ .Values.offsite.accessKeyIdKey | quote }}
- name: RCLONE_CONFIG_OFFSITE_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.offsite.secret | quote }}
      key: {{ .Values.offsite.secretAccessKeyKey | quote }}
- name: RCLONE_CONFIG_OFFSITECRYPT_TYPE
  value: crypt
- name: RCLONE_CONFIG_OFFSITECRYPT_REMOTE
  value: {{ printf "offsite:%s/%s" .Values.offsite.bucket .Values.offsite.pvcPrefix | quote }}
- name: OWNSUITE_CRYPT_PASSPHRASE
  valueFrom:
    secretKeyRef:
      name: {{ .Values.offsite.secret | quote }}
      key: {{ .Values.offsite.cryptPassphraseKey | quote }}
{{- end -}}

{{/*
The sync script. $1 = direction (backup|restore), $2 = the off-site sub-path (the
pvcName). The local copy lives at /data/<SUBPATH>, set via the SUBPATH env. Obscures
the crypt passphrase, then syncs the mounted subtree against its crypt sub-path.
*/}}
{{- define "pvc-backup.script" -}}
set -euo pipefail
RCLONE_CONFIG_OFFSITECRYPT_PASSWORD="$(rclone obscure "$OWNSUITE_CRYPT_PASSPHRASE")"
export RCLONE_CONFIG_OFFSITECRYPT_PASSWORD
direction="$1"
name="$2"
local_path="/data/$SUBPATH"
case "$direction" in
  backup)  src="$local_path"; dst="offsitecrypt:$name" ;;
  restore) src="offsitecrypt:$name"; dst="$local_path"; mkdir -p "$local_path" ;;
  *) echo "usage: sync.sh backup|restore <name>" >&2; exit 2 ;;
esac
echo "==> rclone $direction: $src -> $dst"
rclone sync "$src" "$dst" --create-empty-src-dirs -v
echo "==> done"
{{- end -}}
