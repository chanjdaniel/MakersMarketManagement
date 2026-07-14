# Vercel Deployment Guide for Flask + MongoDB

## Configuration Summary

### Vercel Settings
- **Framework Preset**: `Other` or `Python` (Vercel auto-detects Flask)
- **Build Command**: (leave empty - Vercel auto-detects)
- **Output Directory**: (leave empty)
- **Install Command**: `pip install -r requirements.txt`
- **Python Version**: 3.11 or 3.12 (set in Vercel dashboard or via `runtime.txt`)

### Environment Variables

Set these in your Vercel project settings:

#### Required for Production:
```
SECRET_KEY=your-strong-secret-key-here
SESSION_TYPE=null
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/conventioner?retryWrites=true&w=majority
# Note: MONGODB_URI is automatically set if you use MongoDB Atlas integration from Vercel Marketplace
FRONTEND_URL=https://your-frontend-domain.vercel.app
RECAPTCHA_SECRET_KEY=your-recaptcha-secret-key
CORS_ALLOWED_ORIGINS=https://your-frontend-domain.vercel.app
RESEND_API_KEY=your-resend-api-key
```

`SECRET_KEY`, `RECAPTCHA_SECRET_KEY`, `CORS_ALLOWED_ORIGINS` and `RESEND_API_KEY` are **boot-time requirements**: the function refuses to start without them, so a deployment that is missing one serves nothing at all.
See [RELEASING.md](./RELEASING.md#pre-deploy-required-production-environment) for what each one defends and what an unset value would do.

`SESSION_TYPE=null` is not optional on Vercel: sessions default to the filesystem, and a serverless function has no filesystem that outlives a request.
Nothing keys on `FLASK_ENV` any more - it defaulted to `development` in our own image, so every check that read it was exempting the deployments it existed for. Set the variables above by name instead.

#### Optional (if using individual MongoDB params instead of URI):
```
MONGODB_HOST=your-mongodb-host
MONGODB_PORT=27017
MONGODB_USER=your-username
MONGODB_PASSWORD=your-password
MONGODB_DB=conventioner
MONGODB_AUTH_DB=admin
```

#### Other Services:
```
FROM_EMAIL=your-verified-email@domain.com
```
`RESEND_API_KEY` belongs with the required variables above, not here: without it no organizer can register, verify an address, reset a password, or receive an OTP, so the app refuses to boot rather than serve that.

## Important Notes

### Session Storage
- **For Vercel**: Use `SESSION_TYPE=null` (sessions stored in cookies only)
- **For Local Dev**: Use `SESSION_TYPE=filesystem` (default)
- Filesystem sessions don't work on Vercel's serverless platform

### MongoDB Connection

**Option 1: MongoDB Atlas Integration (Recommended - Easiest)**
- **Provision MongoDB Atlas directly from Vercel**: 
  - Go to Vercel Dashboard → Click "Add new" → "Integration"
  - Search for "MongoDB Atlas" in the Marketplace
  - Select your project and provision a cluster (Free, Dedicated, or Flex)
  - The `MONGODB_URI` environment variable is **automatically configured** for you
  - No separate MongoDB Atlas signup needed - account is created automatically
  - Billing can be managed through Vercel

**Option 2: Manual MongoDB Atlas Setup**
- Create account at https://www.mongodb.com/cloud/atlas
- Create a free cluster (M0)
- Configure network access (allow 0.0.0.0/0 for development or Vercel IPs)
- Create database user
- Get connection string and manually add `MONGODB_URI` to Vercel environment variables
- Connection string format: `mongodb+srv://username:password@cluster.mongodb.net/conventioner?retryWrites=true&w=majority`

### Deployment Steps

1. **Connect your repository to Vercel**
   - Go to Vercel dashboard (https://vercel.com/dashboard)
   - Click "Add New Project"
   - Import your Git repository
   - **Set Root Directory**: `back-end` (if deploying only backend)

2. **Provision MongoDB Atlas (Recommended Method)**
   - In your Vercel project, click "Add new" → "Integration"
   - Search for "MongoDB Atlas" in the Marketplace
   - Select your project and choose a cluster type (Free tier available)
   - The `MONGODB_URI` environment variable will be automatically added to your project
   - **Note**: If you need to specify the database name, you may need to update the URI to include `/conventioner` at the end

3. **Configure Project Settings in Vercel UI**
   - **Framework Preset**: Select `Other` (Vercel will auto-detect Flask)
   - **Build Command**: Leave empty (Vercel auto-detects)
   - **Output Directory**: Leave empty
   - **Install Command**: `pip install -r requirements.txt`
   - **Python Version**: Set to `3.11` or `3.12` in Project Settings > General

4. **Configure Environment Variables**
   - Go to Project Settings > Environment Variables
   - Add the following required variables (if not already set by MongoDB Atlas integration):
     - `SECRET_KEY=your-strong-secret-key-here`
     - `SESSION_TYPE=null`
     - `FRONTEND_URL=https://your-frontend-domain.vercel.app`
     - `RESEND_API_KEY=your-resend-api-key`
     - `FROM_EMAIL=your-verified-email@domain.com`
     - `RECAPTCHA_SECRET_KEY=your-recaptcha-secret-key`
     - `CORS_ALLOWED_ORIGINS=https://your-frontend-domain.vercel.app`
   - **Note**: `MONGODB_URI` should already be set if you used the MongoDB Atlas integration
   - **Note**: `SECRET_KEY`, `RECAPTCHA_SECRET_KEY`, `CORS_ALLOWED_ORIGINS` and `RESEND_API_KEY` are checked at import. Miss one and the function does not boot; the log names every one that is missing.
   - Apply to Production, Preview, and Development environments as needed

5. **Initialize / migrate the database** (before the first deploy, and before any deploy that carries a new migration)
   - The back end refuses to boot unless the market-key migration is recorded as applied, and that check runs at import - so on Vercel it runs on every cold start, and an unmigrated database fails every request rather than serving markets it can only half see.
   - `mongo-init.js` never runs against Atlas (it is the Docker Mongo entrypoint), so a freshly provisioned cluster has no marker. Run this once, from `back-end/`, with `MONGODB_URI` pointing at the Atlas cluster:
     ```bash
     python init_database.py                              # fresh cluster: creates collections and indexes, records the marker
     python migrations/migrate_market_keys.py             # existing data: rewrites markets under the canonical keys
     python migrations/create_applications_collection.py  # existing data: the applications collection and its `market_id` index
     ```
   - See [RELEASING.md](./RELEASING.md#pre-deploy-database-migrations) for the full pre-deploy migration list. Migrations are never run automatically.

6. **Deploy**
   - Click "Deploy" or push to your main branch
   - Vercel will automatically detect Flask and deploy

### File Structure
```
back-end/
├── app.py              # Flask application (entry point - auto-detected by Vercel)
├── requirements.txt    # Python dependencies
├── runtime.txt         # Python version (optional, can also set in UI)
└── ...                 # Other application files
```

### Troubleshooting

- **Import Errors**: Ensure all dependencies are in `requirements.txt`
- **MongoDB Connection Issues**: Check your MongoDB Atlas network access settings
- **Session Issues**: Verify `SESSION_TYPE=null` is set for Vercel. Sessions default to the filesystem, which a serverless function does not keep between requests.
- **CORS Issues**: Ensure `CORS_ALLOWED_ORIGINS` lists your frontend's origin exactly as the browser sends it (`https://your-frontend-domain.vercel.app` - scheme and host, no trailing slash, no path). A preview deployment served from a different domain is a different origin and has to be listed too. `FRONTEND_URL` is only used for the links in outgoing mail and has no say in CORS.
- **"Refusing to start: N of the things this app's public surface rests on are not configured"**: one or more of `SECRET_KEY`, `RECAPTCHA_SECRET_KEY`, `CORS_ALLOWED_ORIGINS`, `RESEND_API_KEY` is unset. The log names every one of them, and each names what it defends or delivers. Set them and redeploy; do not work around it by setting `ALLOW_INSECURE_LOCAL_DEV`, which turns all of that off. See [RELEASING.md](./RELEASING.md#pre-deploy-required-production-environment).
- **"The market-key migration has not been applied to this database"**: the function is refusing to boot because it cannot confirm the migration (see step 5 above). Run `migrations/migrate_market_keys.py` against the Atlas database and redeploy. The same error appears when the marker simply cannot be read - an unknown migration state is treated as unmigrated - so check network access too.
