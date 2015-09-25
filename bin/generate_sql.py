#!/usr/bin/env python

import re
import argparse

parser = argparse.ArgumentParser(description='Generate necessary SQL')
parser.add_argument('--dbname', default='LIGHTNING')
parser.add_argument('--item', default='database')
args = parser.parse_args()

if args.item == 'database':
    sql = """
    USE [master]

    IF  EXISTS (SELECT name FROM sys.databases WHERE name = N'__DBNAME__')
    DROP DATABASE [__DBNAME__]

    USE [master]

    CREATE DATABASE [__DBNAME__] ON  PRIMARY
    ( NAME = N'__DBNAME__', FILENAME = N'C:\Program Files\Microsoft SQL Server\MSSQL10.MSSQLSERVER\MSSQL\DATA\__DBNAME__.mdf' , SIZE = 2048KB , MAXSIZE = UNLIMITED, FILEGROWTH = 1024KB )
     LOG ON
    ( NAME = N'__DBNAME___log', FILENAME = N'C:\Program Files\Microsoft SQL Server\MSSQL10.MSSQLSERVER\MSSQL\DATA\__DBNAME___log.ldf' , SIZE = 1024KB , MAXSIZE = 2048GB , FILEGROWTH = 10%)

    ALTER DATABASE [__DBNAME__] SET COMPATIBILITY_LEVEL = 100

    IF (1 = FULLTEXTSERVICEPROPERTY('IsFullTextInstalled'))
    BEGIN
        EXEC [__DBNAME__].[dbo].[sp_fulltext_database] @action = 'enable'
    END

    ALTER DATABASE [__DBNAME__] SET ANSI_NULL_DEFAULT OFF
    ALTER DATABASE [__DBNAME__] SET ANSI_NULLS OFF
    ALTER DATABASE [__DBNAME__] SET ANSI_PADDING OFF
    ALTER DATABASE [__DBNAME__] SET ANSI_WARNINGS OFF
    ALTER DATABASE [__DBNAME__] SET ARITHABORT OFF
    ALTER DATABASE [__DBNAME__] SET AUTO_CLOSE OFF
    ALTER DATABASE [__DBNAME__] SET AUTO_CREATE_STATISTICS ON
    ALTER DATABASE [__DBNAME__] SET AUTO_SHRINK OFF
    ALTER DATABASE [__DBNAME__] SET AUTO_UPDATE_STATISTICS ON
    ALTER DATABASE [__DBNAME__] SET CURSOR_CLOSE_ON_COMMIT OFF
    ALTER DATABASE [__DBNAME__] SET CURSOR_DEFAULT  GLOBAL
    ALTER DATABASE [__DBNAME__] SET CONCAT_NULL_YIELDS_NULL OFF
    ALTER DATABASE [__DBNAME__] SET NUMERIC_ROUNDABORT OFF
    ALTER DATABASE [__DBNAME__] SET QUOTED_IDENTIFIER OFF
    ALTER DATABASE [__DBNAME__] SET RECURSIVE_TRIGGERS OFF
    ALTER DATABASE [__DBNAME__] SET  DISABLE_BROKER
    ALTER DATABASE [__DBNAME__] SET AUTO_UPDATE_STATISTICS_ASYNC OFF
    ALTER DATABASE [__DBNAME__] SET DATE_CORRELATION_OPTIMIZATION OFF
    ALTER DATABASE [__DBNAME__] SET TRUSTWORTHY OFF
    ALTER DATABASE [__DBNAME__] SET ALLOW_SNAPSHOT_ISOLATION OFF
    ALTER DATABASE [__DBNAME__] SET PARAMETERIZATION SIMPLE
    ALTER DATABASE [__DBNAME__] SET READ_COMMITTED_SNAPSHOT OFF
    ALTER DATABASE [__DBNAME__] SET HONOR_BROKER_PRIORITY OFF
    ALTER DATABASE [__DBNAME__] SET  READ_WRITE
    ALTER DATABASE [__DBNAME__] SET RECOVERY FULL
    ALTER DATABASE [__DBNAME__] SET  MULTI_USER
    ALTER DATABASE [__DBNAME__] SET PAGE_VERIFY CHECKSUM
    ALTER DATABASE [__DBNAME__] SET DB_CHAINING OFF
    """
elif args.item == 'table':
    sql = """
    USE [__DBNAME__]

    SET ANSI_NULLS ON
    SET QUOTED_IDENTIFIER ON

    IF EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[View]') AND type in (N'U'))
    DROP TABLE [dbo].[View]

    IF EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[Limit]') AND type in (N'U'))
    DROP TABLE [dbo].[Limit]

    IF EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[StreamCache]') AND type in (N'U'))
    DROP TABLE [dbo].[StreamCache]

    IF EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[GranularData]') AND type in (N'U'))
    DROP TABLE [dbo].[GranularData]

    IF EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[UserData]') AND type in (N'U'))
    DROP TABLE [dbo].[UserData]

    IF EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[ExpiredAuthorization]') AND type in (N'U'))
    DROP TABLE [dbo].[ExpiredAuthorization]

    IF EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[Authorization]') AND type in (N'U'))
    DROP TABLE [dbo].[Authorization]

    IF EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[InflightAuthorization]') AND type in (N'U'))
    DROP TABLE [dbo].[InflightAuthorization]

    CREATE TABLE [dbo].[InflightAuthorization](
        [id] [BIGINT] IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [service_name] [nvarchar](100) NOT NULL,
        [request_token] [nvarchar](max) NULL,
        [secret] [nvarchar](max) NULL,
        [state] [nvarchar](max) NULL
    ) ON [PRIMARY]

    CREATE TABLE [dbo].[Authorization](
        [id] [BIGINT] IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [uuid] [nchar](36) NOT NULL,
        [client_name] [nvarchar](100) NOT NULL,
        [service_name] [nvarchar](100) NOT NULL,
        [user_id] [nvarchar](100) NOT NULL,
        [token] [nvarchar](max) NOT NULL,
        [refresh_token] [nvarchar](max) NULL,
        [redirect_uri] [nvarchar](max) NULL,
        [secret] [nvarchar](max) NULL,
        [expired_on_timestamp] bigint NULL,
        [account_created_timestamp] bigint NULL
    ) ON [PRIMARY]
    ALTER TABLE [dbo].[Authorization]
        ADD CONSTRAINT UX_Authorization_UUID UNIQUE(uuid)

    ALTER TABLE [dbo].[Authorization]
        ADD CONSTRAINT UX_Authorization_csu UNIQUE(client_name, service_name, user_id)

    CREATE TABLE [dbo].[UserData](
        [id] [BIGINT] IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [uuid] [nchar](36) NOT NULL,
        [method] [nvarchar](100) NOT NULL,
        [timestamp] [bigint] NOT NULL,
        [data] [nvarchar](max) NULL
    ) ON [PRIMARY]

    ALTER TABLE [dbo].[UserData]
        ADD CONSTRAINT UX_UserData_uuid_method_ts UNIQUE(uuid, method, timestamp)
    ALTER TABLE [dbo].[UserData]
        ADD CONSTRAINT FK_UserData_uuid FOREIGN KEY (uuid) REFERENCES [Authorization] (uuid) ON DELETE CASCADE

    CREATE TABLE [dbo].[GranularData](
        [id] [BIGINT] IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [uuid] [nchar](36) NOT NULL,
        [method] [nvarchar](100) NOT NULL,
        [item_id] [nvarchar](100) NOT NULL,
        [actor_id] [nvarchar](100) NOT NULL,
        [timestamp] [bigint] NOT NULL
    ) ON [PRIMARY]

    ALTER TABLE [dbo].[GranularData]
        ADD CONSTRAINT FK_GranularData_uuid FOREIGN KEY (uuid) REFERENCES [Authorization] (uuid) ON DELETE CASCADE

    CREATE TABLE [dbo].[StreamCache](
        [id] [BIGINT] IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [uuid] [nchar](36) NOT NULL FOREIGN KEY REFERENCES [Authorization] (uuid),
        [item_id] [nvarchar](100) NOT NULL,
        [timestamp] [bigint] NOT NULL,
        [data] [text] NOT NULL
    ) ON [PRIMARY]

    ALTER TABLE [dbo].[StreamCache]
        ADD CONSTRAINT FK_StreamCache_uuid FOREIGN KEY (uuid) REFERENCES [Authorization] (uuid) ON DELETE CASCADE

    CREATE TABLE [dbo].[Limit](
        [id] [BIGINT] IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [uuid] [nchar](36) NOT NULL FOREIGN KEY REFERENCES [Authorization] (uuid),
        [last_called_on] [bigint] NOT NULL
    ) ON [PRIMARY]

    ALTER TABLE [dbo].[Limit]
        ADD CONSTRAINT FK_Limit_uuid FOREIGN KEY (uuid) REFERENCES [Authorization] (uuid) ON DELETE CASCADE

    CREATE TABLE [dbo].[View](
        [id] [BIGINT] IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [name] [nvarchar](100) NOT NULL,
        [definition] [nvarchar](max) NOT NULL
    ) ON [PRIMARY]
    """

print re.sub('__DBNAME__', args.dbname, sql)
