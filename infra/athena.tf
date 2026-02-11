# =============================================================================
# ATHENA CONFIGURATION FOR NEWS ANALYTICS
# =============================================================================
# This file sets up AWS Athena for querying news articles stored in S3.
# Athena is a serverless query service - pay only for data scanned ($5 per TB).
#
# Architecture:
# - Glue Data Catalog: Metadata about tables (schema, partitions, location)
# - Athena Workgroup: Query execution settings (result location, encryption)
# - Partition Projection: Auto-discover partitions without MSCK REPAIR (faster, cheaper)

# =============================================================================
# GLUE DATABASE
# =============================================================================

# Glue database: Container for table metadata
# Not a real database - just organizes tables in the catalog
resource "aws_glue_catalog_database" "news_analytics" {
  name        = "${var.project_name}_${var.environment}"
  description = "News analytics articles database for Athena queries"

  # S3 location is optional for Glue DB (each table has its own location)
  catalog_id = data.aws_caller_identity.current.account_id
}

# =============================================================================
# GLUE TABLE FOR NORMALIZED ARTICLES
# =============================================================================

# Glue table: Defines schema and location of Parquet files
# Athena reads this to know how to query the S3 data
resource "aws_glue_catalog_table" "normalized_articles" {
  name          = "normalized_articles"
  database_name = aws_glue_catalog_database.news_analytics.name
  description   = "Normalized news articles in Parquet format"

  table_type = "EXTERNAL_TABLE" # Data in S3, not in Glue

  parameters = {
    "projection.enabled"           = "true"
    "projection.year.type"         = "integer"
    "projection.year.range"        = "2024,2030" # Adjust range as needed
    "projection.month.type"        = "integer"
    "projection.month.range"       = "1,12"
    "projection.month.digits"      = "2"
    "projection.day.type"          = "integer"
    "projection.day.range"         = "1,31"
    "projection.day.digits"        = "2"
    "projection.source.type"       = "enum"
    "projection.source.values"     = "newsapi,guardian,nytimes,unknown"
    "storage.location.template"    = "s3://${aws_s3_bucket.normalized_articles.id}/normalized/year=$${year}/month=$${month}/day=$${day}/source=$${source}"
    "classification"               = "parquet"
    "parquet.compression"          = "SNAPPY"
  }

  # Partition keys: Used in WHERE clauses for efficient filtering
  # Partition projection automatically creates partitions based on these
  partition_keys {
    name = "year"
    type = "int"
    comment = "Year of article publication"
  }

  partition_keys {
    name = "month"
    type = "int"
    comment = "Month of article publication"
  }

  partition_keys {
    name = "day"
    type = "int"
    comment = "Day of article publication"
  }

  partition_keys {
    name = "source"
    type = "string"
    comment = "Article source (newsapi, guardian, etc.)"
  }

  # Storage descriptor: Defines file format and schema
  storage_descriptor {
    location      = "s3://${aws_s3_bucket.normalized_articles.id}/normalized/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      
      parameters = {
        "serialization.format" = "1"
      }
    }

    # Column definitions: Must match Parquet schema
    columns {
      name    = "source"
      type    = "string"
      comment = "API source (newsapi, guardian, etc.)"
    }

    columns {
      name    = "source_name"
      type    = "string"
      comment = "Publisher name (bbc, cnn, etc.)"
    }

    columns {
      name    = "title"
      type    = "string"
      comment = "Article title"
    }

    columns {
      name    = "description"
      type    = "string"
      comment = "Article description/summary"
    }

    columns {
      name    = "url"
      type    = "string"
      comment = "Article URL"
    }

    columns {
      name    = "published_at"
      type    = "timestamp"
      comment = "Publication timestamp"
    }

    columns {
      name    = "topic"
      type    = "string"
      comment = "Search topic/query used"
    }

    columns {
      name    = "article_hash"
      type    = "string"
      comment = "Deduplication hash (SHA256)"
    }

    columns {
      name    = "ingested_at"
      type    = "timestamp"
      comment = "When article was ingested into our system"
    }
  }
}

# =============================================================================
# ATHENA WORKGROUP
# =============================================================================

# Workgroup: Isolated environment for query execution
# Benefits:
# - Control query costs with limits
# - Separate dev/prod query execution
# - Configure result location and encryption
resource "aws_athena_workgroup" "news_analytics" {
  name        = "${var.project_name}-${var.environment}"
  description = "Workgroup for news analytics queries"
  state       = "ENABLED"

  configuration {
    # Enforce workgroup settings (users can't override)
    enforce_workgroup_configuration = true

    # Query results configuration
    result_configuration {
      output_location = "s3://${aws_s3_bucket.athena_results.id}/query-results/"

      # Enable encryption for query results
      encryption_configuration {
        encryption_option = "SSE_S3" # AWS-managed encryption
      }
    }

    # Query execution limits (cost control)
    # bytes_scanned_cutoff_per_query = 10737418240 # 10 GB limit per query (uncomment to enable)

    # Enable query result reuse (cache) for 24 hours
    # Rerunning same query returns cached result (saves $$$)
    # Note: Result reuse is enabled by default in Athena
  }

  tags = merge(var.tags, {
    Name        = "${var.project_name}-${var.environment}-workgroup"
    Description = "Athena workgroup for analytics queries"
  })
}

# =============================================================================
# ATHENA NAMED QUERIES (TEMPLATES)
# =============================================================================

# Named query: Count articles by source
# Users can run this from Athena console or via API
resource "aws_athena_named_query" "count_by_source" {
  name        = "${var.project_name}_count_articles_by_source"
  description = "Count total articles grouped by source"
  database    = aws_glue_catalog_database.news_analytics.name
  workgroup   = aws_athena_workgroup.news_analytics.id

  query = <<-SQL
    SELECT 
      source,
      COUNT(*) as article_count,
      COUNT(DISTINCT source_name) as publisher_count,
      MIN(published_at) as oldest_article,
      MAX(published_at) as newest_article
    FROM ${aws_glue_catalog_table.normalized_articles.name}
    WHERE year = YEAR(CURRENT_DATE)
      AND month = MONTH(CURRENT_DATE)
    GROUP BY source
    ORDER BY article_count DESC;
  SQL
}

# Named query: Trending topics in last 7 days
resource "aws_athena_named_query" "trending_topics" {
  name        = "${var.project_name}_trending_topics"
  description = "Find most common topics in the last 7 days"
  database    = aws_glue_catalog_database.news_analytics.name
  workgroup   = aws_athena_workgroup.news_analytics.id

  query = <<-SQL
    SELECT 
      topic,
      COUNT(*) as article_count,
      COUNT(DISTINCT source_name) as sources_covering
    FROM ${aws_glue_catalog_table.normalized_articles.name}
    WHERE published_at >= CURRENT_DATE - INTERVAL '7' DAY
      AND topic IS NOT NULL
    GROUP BY topic
    ORDER BY article_count DESC
    LIMIT 20;
  SQL
}

# Named query: Daily article volume
resource "aws_athena_named_query" "daily_volume" {
  name        = "${var.project_name}_daily_article_volume"
  description = "Count articles per day for the last 30 days"
  database    = aws_glue_catalog_database.news_analytics.name
  workgroup   = aws_athena_workgroup.news_analytics.id

  query = <<-SQL
    SELECT 
      DATE(published_at) as date,
      COUNT(*) as article_count,
      COUNT(DISTINCT source_name) as unique_publishers
    FROM ${aws_glue_catalog_table.normalized_articles.name}
    WHERE published_at >= CURRENT_DATE - INTERVAL '30' DAY
    GROUP BY DATE(published_at)
    ORDER BY date DESC;
  SQL
}

# =============================================================================
# OUTPUTS
# =============================================================================

output "glue_database_name" {
  description = "Name of the Glue database"
  value       = aws_glue_catalog_database.news_analytics.name
}

output "glue_table_name" { 
  description = "Name of the Glue table for normalized articles"
  value       = aws_glue_catalog_table.normalized_articles.name
}

output "athena_workgroup_arn" {
  description = "ARN of the Athena workgroup"
  value       = aws_athena_workgroup.news_analytics.arn
}
