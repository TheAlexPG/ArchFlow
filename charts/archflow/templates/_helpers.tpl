{{/*
Expand the name of the chart.
*/}}
{{- define "archflow.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "archflow.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "archflow.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "archflow.labels" -}}
app.kubernetes.io/name: {{ include "archflow.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
