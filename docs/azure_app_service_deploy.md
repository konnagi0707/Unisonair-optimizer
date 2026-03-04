# Azure 部署指南（App Service + GitHub Pages 前端）

目标:

- 后端 API 部署到 Azure App Service（Linux 容器）
- 前端继续使用 GitHub Pages 页面
- 通过 `?api_base=` 把 Pages 前端指向 Azure API

---

## 1. 前置条件

- 已安装并登录 Azure CLI:

```bash
az login
az account show
```

- 本地仓库可正常运行，且已准备数据源（`masters/`、`catalogs/`、`UOA大表 新人必看.xlsx`）。
- 已安装 Docker（仅本地打包时需要；`az acr build` 可直接用云端构建）。

---

## 2. 打包数据集

```bash
./deploy/make_dataset_bundle.sh
```

输出示例:

- `deploy/dist/uoa_dataset_YYYYmmdd_HHMMSS.tar.gz`

---

## 3. 上传数据包到 Azure Blob 并生成 URL

设置变量（示例）:

```bash
export AZ_RESOURCE_GROUP=uoa-rg
export AZ_LOCATION=eastasia
export AZ_STORAGE_ACCOUNT=uoadata123456
export AZ_STORAGE_CONTAINER=uoa-dataset
export AZ_SAS_EXPIRY=2030-01-01T00:00Z
```

执行:

```bash
./deploy/azure_upload_dataset_blob.sh
```

输出:

- `UOA_DATA_TARBALL_URL`（带只读 SAS 的直链）
- 自动写入 `deploy/dist/azure_dataset_url.txt`

---

## 4. 部署后端到 Azure App Service

设置变量（示例）:

```bash
export AZ_RESOURCE_GROUP=uoa-rg
export AZ_LOCATION=eastasia
export AZ_APP_SERVICE_PLAN=uoa-linux-plan
export AZ_APP_SERVICE_SKU=B1
export AZ_WEBAPP_NAME=uoa-optimizer-demo
export AZ_ACR_NAME=uoaacr123456
export AZ_IMAGE_NAME=uoa-scoring
export AZ_IMAGE_TAG=latest

export UOA_DATA_TARBALL_URL="$(cat deploy/dist/azure_dataset_url.txt)"
```

执行:

```bash
./deploy/azure_deploy_app_service.sh
```

脚本会自动完成:

1. 创建/复用 Resource Group
2. 创建/复用 ACR 并云端构建镜像
3. 创建/复用 Linux App Service Plan + Web App
4. 配置容器镜像与 ACR 凭据
5. 设置关键环境变量:
   - `WEBSITES_PORT=10000`
   - `PORT=10000`
   - `WEBSITES_ENABLE_APP_SERVICE_STORAGE=true`
   - `UOA_RUNTIME_DATA_DIR=/home/site/runtime`
   - `UOA_DATA_ROOT=/home/site/dataset`
   - `UOA_DATA_TARBALL_URL=<blob sas url>`
6. 配置健康检查 `/api/healthz`
7. 重启服务

---

## 5. 验证

后端健康检查:

```bash
curl "https://<你的webapp>.azurewebsites.net/api/healthz"
```

返回 `{"ok":true}` 即成功。

---

## 6. 连接 GitHub Pages 前端

打开:

```text
https://konnagi0707.github.io/Unisonair-optimizer/?api_base=https://<你的webapp>.azurewebsites.net
```

说明:

- 前端会把所有 `/api/*` 请求发往 `api_base` 指定的地址。
- 结果页、账号读写、优化任务都走 Azure 后端。

---

## 7. 成本建议（先稳再省）

- `B1` 是最稳妥起步档（Linux 容器可用，冷启动和内存都够）。
- 如果只有自己使用，可后续再下调或改到更省的容器平台。

---

## 8. 常见问题

1. 启动失败/反复重启
   - 先看 `Log stream`。
   - 常见原因是 `UOA_DATA_TARBALL_URL` 不可下载或数据包结构不对。

2. 页面能打开但接口报错
   - 确认 URL 带了 `?api_base=https://<webapp域名>`。
   - 确认后端 `/api/healthz` 正常。

3. 更新了 `masters/catalogs/xlsx` 后没生效
   - 重新执行:
     - `./deploy/make_dataset_bundle.sh`
     - `./deploy/azure_upload_dataset_blob.sh`
   - 更新 `UOA_DATA_TARBALL_URL` 后重启 Web App。

---

## 9. 自动同步 workbook 并刷新 Azure

新增脚本:

- `deploy/sync_workbook_to_azure.sh`
- `deploy/azure_refresh_dataset.sh`

### 9.1 一键同步（下载 -> 打包 -> 上传 -> 重启）

```bash
export WORKBOOK_SOURCE_URL='https://<direct-file-url>.xlsx'
export AZ_RESOURCE_GROUP=uoa-rg
export AZ_STORAGE_ACCOUNT=<你的storage账号>
export AZ_WEBAPP_NAME=<你的webapp名称>

./deploy/sync_workbook_to_azure.sh
```

说明:

- 仅当 workbook 的 sha256 变化时才继续部署。
- 若下载到的是 HTML（例如分享页），脚本会直接报错并退出。
- 可选鉴权:
  - `WORKBOOK_AUTH_HEADER='Authorization: Bearer <token>'`
  - `WORKBOOK_COOKIE='<cookie-string>'`

### 9.2 仅刷新 Azure 数据 URL（不重新下载）

```bash
export UOA_DATA_TARBALL_URL="$(cat deploy/dist/azure_dataset_url.txt)"
export AZ_RESOURCE_GROUP=uoa-rg
export AZ_WEBAPP_NAME=<你的webapp名称>

./deploy/azure_refresh_dataset.sh
```

---

## 10. 账号数据存储位置（重要）

- GitHub Pages 只是前端页面，不存后端账号 JSON。
- 前端账号固定为本地模式（`localStorage`），不会写入 Azure。
- Azure 上的账号 JSON 路径（若历史版本写入过）:
  - `/home/site/runtime/account_profiles.json`
  - `/home/site/runtime/account_profiles_backups/`

结论:

- 每台设备各自保存，互不共享。
- 若要清理历史云端账号数据，可调用后端删除接口或直接删除 runtime 目录中的账号文件。
