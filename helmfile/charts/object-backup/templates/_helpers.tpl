{{/*
rclone remote configuration as env vars (RCLONE_CONFIG_<REMOTE>_<KEY>), shared by the
backup CronJob and the restore Job. Three remotes:
  - primary       : the live media store (S3-compatible: Garage or external S3)
  - offsite       : the off-site backup store (S3-compatible)
  - offsitecrypt  : a crypt overlay on offsite:<bucket>/<mediaPrefix> for client-side
                    encryption (ADR-017). Its password is obscured at runtime from
                    OWNSUITE_CRYPT_PASSPHRASE (rclone wants an obscured value).
Credentials come from secretKeyRef; endpoints/regions/buckets are plain config.
*/}}
{{- define "object-backup.env" -}}
- name: RCLONE_CONFIG_PRIMARY_TYPE
  value: s3
- name: RCLONE_CONFIG_PRIMARY_PROVIDER
  value: Other
- name: RCLONE_CONFIG_PRIMARY_ENDPOINT
  value: {{ .Values.primary.endpoint | quote }}
- name: RCLONE_CONFIG_PRIMARY_REGION
  value: {{ .Values.primary.region | quote }}
- name: RCLONE_CONFIG_PRIMARY_FORCE_PATH_STYLE
  value: "true"
- name: RCLONE_CONFIG_PRIMARY_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef:
      name: {{ .Values.primary.secret | quote }}
      key: {{ .Values.primary.accessKeyIdKey | quote }}
- name: RCLONE_CONFIG_PRIMARY_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.primary.secret | quote }}
      key: {{ .Values.primary.secretAccessKeyKey | quote }}
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
  value: {{ printf "offsite:%s/%s" .Values.offsite.bucket .Values.offsite.mediaPrefix | quote }}
- name: PRIMARY_BUCKET
  value: {{ .Values.primary.bucket | quote }}
- name: OWNSUITE_CRYPT_PASSPHRASE
  valueFrom:
    secretKeyRef:
      name: {{ .Values.offsite.secret | quote }}
      key: {{ .Values.offsite.cryptPassphraseKey | quote }}
{{- end -}}

{{/*
The sync script. $1 = direction (backup|restore). Obscures the crypt passphrase into
the form rclone expects, then syncs between primary:<bucket> and the crypt overlay.
*/}}
{{- define "object-backup.script" -}}
set -euo pipefail
RCLONE_CONFIG_OFFSITECRYPT_PASSWORD="$(rclone obscure "$OWNSUITE_CRYPT_PASSPHRASE")"
export RCLONE_CONFIG_OFFSITECRYPT_PASSWORD
direction="$1"
case "$direction" in
  backup)  src="primary:$PRIMARY_BUCKET"; dst="offsitecrypt:" ;;
  restore) src="offsitecrypt:"; dst="primary:$PRIMARY_BUCKET" ;;
  *) echo "usage: sync.sh backup|restore" >&2; exit 2 ;;
esac
echo "==> rclone $direction: $src -> $dst"
rclone sync "$src" "$dst" --s3-no-check-bucket --create-empty-src-dirs -v
echo "==> done"
{{- end -}}
