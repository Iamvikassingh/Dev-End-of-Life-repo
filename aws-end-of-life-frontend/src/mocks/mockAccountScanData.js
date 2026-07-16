/**
 * Mock data for Account Level Scan mode.
 * Represents a single connected AWS account.
 */
const d = (n) => {
  const dt = new Date();
  dt.setDate(dt.getDate() + n);
  return dt.toISOString().slice(0, 10);
};
const SCANNED = new Date().toISOString();
const ACCOUNT_ID   = "123456789012";
const ACCOUNT_NAME = "prod-account";

export const MOCK_ACCOUNT = {
  accountId:   ACCOUNT_ID,
  accountName: ACCOUNT_NAME,
  roleArn:     `arn:aws:iam::${ACCOUNT_ID}:role/EOLMonitorReadOnly`,
  connectedAt: SCANNED,
  regions:     ["us-east-1","us-east-2","us-west-2","eu-west-1","eu-central-1","ap-southeast-1","ap-northeast-1"],
};

export const MOCK_ACCOUNT_INVENTORY = [
  // EOL
  { id:"a1", accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"legacy-processor",   resourceArn:"arn:aws:lambda:us-east-1:123456789012:function:legacy-processor",   service:"Lambda",      region:"us-east-1",    version:"python3.8",      status:"EOL",              eolDate:d(-120), daysToEol:-120, recommendedAction:"Upgrade to python3.12", lastScanned:SCANNED },
  { id:"a2", accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"old-api-handler",    resourceArn:"arn:aws:lambda:us-east-1:123456789012:function:old-api-handler",    service:"Lambda",      region:"us-east-1",    version:"nodejs14.x",     status:"EOL",              eolDate:d(-200), daysToEol:-200, recommendedAction:"Upgrade to nodejs22.x", lastScanned:SCANNED },
  { id:"a3", accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"legacy-eks",         resourceArn:"arn:aws:eks:us-east-1:123456789012:cluster/legacy-eks",             service:"EKS",         region:"us-east-1",    version:"1.26",           status:"EOL",              eolDate:d(-60),  daysToEol:-60,  recommendedAction:"Upgrade to 1.33", lastScanned:SCANNED },
  { id:"a4", accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"postgres-legacy",    resourceArn:"arn:aws:rds:eu-west-1:123456789012:db:postgres-legacy",             service:"RDS_postgres", region:"eu-west-1",    version:"PostgreSQL 11",  status:"EOL",              eolDate:d(-30),  daysToEol:-30,  recommendedAction:"Upgrade to PostgreSQL 16", lastScanned:SCANNED },
  { id:"a5", accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"auth-v1",            resourceArn:"arn:aws:lambda:ap-southeast-1:123456789012:function:auth-v1",        service:"Lambda",      region:"ap-southeast-1",version:"python3.7",      status:"EOL",              eolDate:d(-400), daysToEol:-400, recommendedAction:"Upgrade to python3.12", lastScanned:SCANNED },
  { id:"a6", accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"redis-old",          resourceArn:"arn:aws:elasticache:us-west-2:123456789012:cluster:redis-old",       service:"ElastiCache", region:"us-west-2",    version:"Redis 5.0",      status:"EOL",              eolDate:d(-15),  daysToEol:-15,  recommendedAction:"Upgrade to Redis 7.x", lastScanned:SCANNED },
  { id:"a7",  accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"i-0xlegacy1234abc",  resourceArn:"arn:aws:ec2:us-east-2:123456789012:instance/i-0xlegacy1234abc",      service:"EC2",         region:"us-east-2",    version:"Amazon Linux 1",  status:"EOL",           eolDate:d(-730), daysToEol:-730, recommendedAction:"Migrate to Amazon Linux 2023", lastScanned:SCANNED },
  { id:"a25", accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"web-prod-01",          resourceArn:"arn:aws:ec2:ap-south-1:123456789012:instance/i-0webprod01amz2",       service:"EC2",         region:"ap-south-1",   version:"Amazon Linux 2",  status:"EXPIRING_SOON", eolDate:d(26),   daysToEol:26,   recommendedAction:"Migrate to Amazon Linux 2023 before 2026-06-30", lastScanned:SCANNED },
  { id:"a26", accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"old-worker-01",        resourceArn:"arn:aws:ec2:ap-south-1:123456789012:instance/i-0centos7worker01x",    service:"EC2",         region:"ap-south-1",   version:"CentOS 7",        status:"EOL",           eolDate:d(-704), daysToEol:-704, recommendedAction:"Migrate to Amazon Linux 2023 or RHEL 9", lastScanned:SCANNED },
  { id:"a27", accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"app-server-01",        resourceArn:"arn:aws:ec2:us-east-1:123456789012:instance/i-0ubuntu2204app01x",     service:"EC2",         region:"us-east-1",    version:"Ubuntu 22.04",    status:"SUPPORTED",     eolDate:d(330),  daysToEol:330,  recommendedAction:null, lastScanned:SCANNED },
  { id:"a28", accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"mystery-box-01",       resourceArn:"arn:aws:ec2:eu-west-1:123456789012:instance/i-0unknownos001xyz",      service:"EC2",         region:"eu-west-1",    version:"Unknown OS",      status:"UNKNOWN",       eolDate:null,    daysToEol:null, recommendedAction:"Enable SSM Inventory or tag OS version for accurate EC2 lifecycle detection", lastScanned:SCANNED },
  // EXPIRING_SOON
  { id:"a8", accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"data-pipeline",      resourceArn:"arn:aws:lambda:us-east-1:123456789012:function:data-pipeline",       service:"Lambda",      region:"us-east-1",    version:"python3.9",      status:"EXPIRING_SOON",    eolDate:d(45),   daysToEol:45,   recommendedAction:"Upgrade to python3.12", lastScanned:SCANNED },
  { id:"a9", accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"image-processor",    resourceArn:"arn:aws:lambda:us-west-2:123456789012:function:image-processor",      service:"Lambda",      region:"us-west-2",    version:"nodejs18.x",     status:"EXPIRING_SOON",    eolDate:d(30),   daysToEol:30,   recommendedAction:"Upgrade to nodejs22.x", lastScanned:SCANNED },
  { id:"a10",accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"staging-cluster",    resourceArn:"arn:aws:eks:us-west-2:123456789012:cluster/staging-cluster",          service:"EKS",         region:"us-west-2",    version:"1.28",           status:"EXPIRING_SOON",    eolDate:d(90),   daysToEol:90,   recommendedAction:"Upgrade to 1.33", lastScanned:SCANNED },
  { id:"a11",accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"mysql-app-db",       resourceArn:"arn:aws:rds:us-east-1:123456789012:db:mysql-app-db",                  service:"RDS_mysql",    region:"us-east-1",    version:"MySQL 8.0",      status:"EXPIRING_SOON",    eolDate:d(120),  daysToEol:120,  recommendedAction:"Upgrade to MySQL 8.4", lastScanned:SCANNED },
  { id:"a12",accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"redis-cache-01",     resourceArn:"arn:aws:elasticache:us-east-1:123456789012:cluster:redis-cache-01",   service:"ElastiCache", region:"us-east-1",    version:"Redis 6.2",      status:"EXPIRING_SOON",    eolDate:d(60),   daysToEol:60,   recommendedAction:"Upgrade to Redis 7.x", lastScanned:SCANNED },
  { id:"a13",accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"dev-cluster",        resourceArn:"arn:aws:eks:eu-central-1:123456789012:cluster/dev-cluster",           service:"EKS",         region:"eu-central-1", version:"1.29",           status:"EXPIRING_SOON",    eolDate:d(75),   daysToEol:75,   recommendedAction:"Upgrade to 1.33", lastScanned:SCANNED },
  { id:"a14",accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"search-logs",        resourceArn:"arn:aws:es:ap-northeast-1:123456789012:domain/search-logs",           service:"OpenSearch",  region:"ap-northeast-1",version:"1.3",            status:"EXPIRING_SOON",    eolDate:d(10),   daysToEol:10,   recommendedAction:"Upgrade to 2.x", lastScanned:SCANNED },
  // EXTENDED_SUPPORT
  { id:"a15",accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"prod-eu-cluster",    resourceArn:"arn:aws:eks:eu-central-1:123456789012:cluster/prod-eu-cluster",       service:"EKS",         region:"eu-central-1", version:"1.27",           status:"EXTENDED_SUPPORT", eolDate:d(200),  daysToEol:200,  recommendedAction:"Plan upgrade to 1.33 before extended support ends", lastScanned:SCANNED },
  { id:"a16",accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"aurora-pg-prod",     resourceArn:"arn:aws:rds:us-east-1:123456789012:cluster:aurora-pg-prod",           service:"Aurora_PostgreSQL", region:"us-east-1", version:"PostgreSQL 13",  status:"EXTENDED_SUPPORT", eolDate:d(250),  daysToEol:250,  recommendedAction:"Upgrade to PostgreSQL 16", lastScanned:SCANNED },
  { id:"a17",accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"mysql-legacy",       resourceArn:"arn:aws:rds:us-east-2:123456789012:db:mysql-legacy",                  service:"RDS_mysql",    region:"us-east-2",    version:"MySQL 8.0",      status:"EXTENDED_SUPPORT", eolDate:d(320),  daysToEol:320,  recommendedAction:"Upgrade to MySQL 8.4", lastScanned:SCANNED },
  { id:"a18",accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"sa-cluster",         resourceArn:"arn:aws:eks:sa-east-1:123456789012:cluster/sa-cluster",               service:"EKS",         region:"sa-east-1",    version:"1.25",           status:"EXTENDED_SUPPORT", eolDate:d(210),  daysToEol:210,  recommendedAction:"Upgrade to 1.33", lastScanned:SCANNED },
  // SUPPORTED (select)
  { id:"a19",accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"auth-service",       resourceArn:"arn:aws:lambda:us-east-1:123456789012:function:auth-service",         service:"Lambda",      region:"us-east-1",    version:"python3.12",     status:"SUPPORTED",        eolDate:d(700),  daysToEol:700,  recommendedAction:null, lastScanned:SCANNED },
  { id:"a20",accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"main-cluster",       resourceArn:"arn:aws:eks:us-east-1:123456789012:cluster/main-cluster",             service:"EKS",         region:"us-east-1",    version:"1.32",           status:"SUPPORTED",        eolDate:d(400),  daysToEol:400,  recommendedAction:null, lastScanned:SCANNED },
  { id:"a21",accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"postgres-main",      resourceArn:"arn:aws:rds:us-east-1:123456789012:db:postgres-main",                 service:"RDS_postgres", region:"us-east-1",    version:"PostgreSQL 16",  status:"SUPPORTED",        eolDate:d(900),  daysToEol:900,  recommendedAction:null, lastScanned:SCANNED },
  { id:"a22",accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"redis-main",         resourceArn:"arn:aws:elasticache:us-east-1:123456789012:cluster:redis-main",        service:"ElastiCache", region:"us-east-1",    version:"Redis 7.1",      status:"SUPPORTED",        eolDate:d(800),  daysToEol:800,  recommendedAction:null, lastScanned:SCANNED },
  { id:"a23",accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"events-cluster",     resourceArn:"arn:aws:kafka:us-east-1:123456789012:cluster/events-cluster/xyz",      service:"MSK",         region:"us-east-1",    version:"Kafka 3.7",      status:"SUPPORTED",        eolDate:d(600),  daysToEol:600,  recommendedAction:null, lastScanned:SCANNED },
  { id:"a24",accountId:ACCOUNT_ID, accountName:ACCOUNT_NAME, resourceName:"search-prod",        resourceArn:"arn:aws:es:us-east-1:123456789012:domain/search-prod",                 service:"OpenSearch",  region:"us-east-1",    version:"2.13",           status:"SUPPORTED",        eolDate:d(550),  daysToEol:550,  recommendedAction:null, lastScanned:SCANNED },
];

export const MOCK_ACCOUNT_SUMMARY = {
  accountId:   ACCOUNT_ID,
  accountName: ACCOUNT_NAME,
  totals:      { EOL: 8, EXPIRING_SOON: 8, EXTENDED_SUPPORT: 4, SUPPORTED: 7, UNKNOWN: 1 },
  regions:     MOCK_ACCOUNT.regions,
  lastScanned: SCANNED,
};

export const MOCK_CONNECTED_ACCOUNTS = [
  {
    id:               "conn-demo-1",
    accountId:        ACCOUNT_ID,
    accountName:      ACCOUNT_NAME,
    roleArn:          `arn:aws:iam::${ACCOUNT_ID}:role/EOLMonitorReadOnly`,
    externalId:       "eolm-DEMO-V6GZW4",
    regions:          "all",
    singleRegion:     "us-east-1",
    selectedRegions:  [],
    connectedAt:      new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
    lastScanAt:       new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    lastScanStatus:   "success",
    lastScanSummary:  { total: 28, EOL: 8, EXPIRING_SOON: 8, EXTENDED_SUPPORT: 4, SUPPORTED: 7, UNKNOWN: 1 },
  },
];
