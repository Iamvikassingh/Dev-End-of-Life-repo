# Changelog

This is a list of major changes in `inspector-sbomgen`.

You can download the latest release of inspector-sbomgen here:
- https://docs.aws.amazon.com/inspector/latest/user/sbom-generator-versions.html

## [1.14.4] - July 13th 2026
- Upgrade Go toolchain from 1.25.11 to 1.25.12.

## [1.14.3] - June 24th 2026
- Minor improvements to Python package collectors to maintain PyPA specifications.
- Minor improvements to .Net Framework package collection.
- Improved Lua plugin file read behavior to confine access to the artifact under inventory.

## [1.14.2] - June 15th 2026
- Files that are symlinks are now excluded from return values in Lua file search functions:
  sbomgen.find_files_by_name
  sbomgen.find_files_by_name_icase
  sbomgen.find_files_by_suffix
  sbomgen.find_files_by_path_regex
  sbomgen.glob_find_files

- Added default scan path, /usr/lib/nodejs*/lib/node_modules, improving NodeJS coverage on Amazon Linux.

## [1.14.1] - June 4th 2026
- Upgrade Go toolchain from 1.25.10 to 1.25.11.

## [1.14.0] - June 2nd 2026

### OS Support
- WizOS PURLs now include `distro=wizos`. 
- Container SBOMs now attach RHEL subscription properties (`subscription:enabled`, `subscription:name`, `subscription:locked_version`) to the operating-system component, matching localhost and volume mode.
- Improved apk package database lookup on Wolfi, Chainguard, and Alpine images.

### Expanded Ecosystems
- Added Cursor IDE detection.
- Added Windsurf IDE detection.
- Added Zed editor detection.

### Plugin API
- Added `hashes` field and hash helpers to `push_package` for emitting component hashes from Lua plugins.
- Deprecated `sbomgen.sha256` in favor of the more general `sbomgen.hash_file` API.
  - `sbomgen.sha256` still functions, but it will be removed in a future release.
- Hardened inputs and processing in `sbomgen.resolve_glob_paths` for cross-user home-directory globbing. 
- Components produced by user-supplied Lua plugins (loaded via `--plugin-dir`) are now marked with CycloneDX `scope: "optional"`, distinguishing them from components produced by official plugins.

### Miscellaneous
- The java-jar scanner now skips directories whose name happens to share a ".jar" suffix.
- Upgraded packageurl-go to v0.1.5.
- Upgraded golang.org/x/crypto to v0.52.0, golang.org/x/net to v0.55.0, and golang.org/x/sys to v0.45.0.
- Improved Debian kernel-tag handling: the `running_kernel` tag is now propagated to cloud kernel meta-packages (e.g. `linux-image-aws`) via the `Depends` field, so the meta-package and its installed kernel image are tagged consistently.
- The scanners.ValidateScanner function now recognizes Lua-plugin scanner names.
- Added a `--max-read-file-size` flag (and matching library `SetMaxReadFileSize` / `GetMaxReadFileSize`) that caps a single buffered `Artifact.ReadFile` call. Oversized files are skipped with a warning. Defaults to 4 GiB; set to 0 to disable.

## [1.13.2] - May 13th 2026
- Improved performance of the docker-binary plugin during localhost scans on systems with large Docker daemons.

## [1.13.1] - May 8th 2026
- Upgrade Go toolchain from 1.25.9 to 1.25.10.
- Upgrade golang.org/x/net from 0.51.0 to 0.53.0.
- Restore scanner coverage for ecosystems ported to embedded Lua plugins in v1.13.0.

## [1.13.0] - May 7th 2026

### Sbomgen Plugin System
- Users can now create Lua plugins to onboard package inventory for ecosystems not presently supported in sbomgen.
- See below for more information about this feature:
  - https://docs.aws.amazon.com/inspector/latest/user/sbomgen-plugin-developer-guide.html

### OS Support
- Added kernel version and architecture to Windows SBOMs.
- Added Bottlerocket application inventory collection in control container.

### Programming Languages
- Added support for Swift package collection.

### Expanded Ecosystems
- Added generic AI/ML model file collector with opt-in `--collect-ml-models` flag.
- Added Ollama CLI model collector (requires --collect-ml-models flag).
- Added AI agent collectors for:
  - Claude Code
  - Kiro CLI
  - GitHub Copilot
  - Amazon Q Developer
  - Ollama
- Added support for Docker binary installations.
- Added support for Conda package environments.
- Added support for Apache Cassandra and Apache Struts installations.
- Expanded default python-pkg localhost scan paths to cover pip install --user and uv tool install layouts (resulted in added support for CrewAI)

### Cloud Metadata
- Added IMDS metadata collection for Google Cloud instances.
- Added Microsoft Entra ID tenant ID to Azure IMDS metadata when a managed identity is assigned to the VM.

### Miscellaneous
- Improved handling of Debian packages with oversized Provides fields.
- Classified malformed container image timestamps as `InvalidImageFormat`.
- Improved HuggingFace model cache discovery outside the default location.

- The follow package collectors have been ported to Lua plugins:
  - curl / libcurl
  - nginx
  - Apache httpd
  - Apache Tomcat
  - OpenSSH
  - Redis
  - MySQL / MariaDB
  - Go toolchain
  - Jenkins
  - MongoDB Server
  - Microsoft SQL Server
  - Atlassian server products (Jira Core, Confluence)
  - Atlassian applications (Jira Software, Service Desk)
  - Google Chrome installations
  - Elasticsearch
  - Node.js runtime
  - HuggingFace models
  - OpenSSL
  - Oracle Database Server
  - Java installations (Amazon Corretto, OpenJDK, JRE)
  - PHP interpreter
  - 7zip
  - WordPress (core, plugins, themes)

## [1.12.2] - April 27th 2026
- Upgrade go.opentelemetry.io/otel from 1.39.0 to 1.41.0.

## [1.12.1] - April 9th 2026
- Upgrade Go toolchain from 1.25.8 to 1.25.9.

## [1.12.0] - March 31st 2026

### Expanded Ecosystems
- Added support for Redis Server installations.
- Added support for MongoDB Server installations.
- Added support for .NET Framework collector on Windows.
- Added support for AI/ML model detection from HuggingFace CLI cache.
- Added support for Python uv.lock package collection.

### OS Support
- Added Bottlerocket OS inventory support for volume scans.
- Added RHEL 10 to EUS/E4S subscription detection scope.
- Improved Amazon Linux vendor detection for packages with `Amazon.com` vendor string.
- Added Ubuntu Pro subscription status collection for localhost and volume scans.

### Container Images
- Added WORKDIR, CMD, and ENTRYPOINT absolute directories into container SBOM metadata.
- Improved network efficiency when scanning remote container images.

### Cloud Metadata
- Added AWS account ID collection via EC2 instance identity document.
- Added `resource_type` property for EC2 instances.
- Added Azure resource group and subscription ID to IMDS metadata.

### Inspector Scan API
- Improved validation to reject zero-component SBOMs with user-friendly error message.
- Empty `components` array is now omitted from SBOM output instead of emitting an empty array.

### Miscellaneous
- Fixed binary scanner hangup on FIFO and special files.
- Improved file filtering in binary scanner.
- Improved MariaDB binary version pattern handling.
- Downgraded "unable to initialize system info" log from ERROR to WARN.
- Added `--debug-file-paths` for per-path directory walk debug logging.
- Preserve file permissions when unpacking archives.

## [1.11.2] - March 11th 2026
- Upgrade Go toolchain from 1.25.7 to 1.25.8.

## [1.11.1] - March 5th 2026
- Upgrade github.com/docker/cli from v29.1.5 to v29.2.0.

## [1.11.0] - February 10th 2026

### Cloud Metadata (localhost artifact type only)
- Expanded host metadata collection to include boot disk ID, boot time, network interfaces, and open ports.
- Added Azure IMDS support when inventorying Azure VMs.
- Added AWS IMDS support when inventorying EC2 Instances.

### Hardened Container Images Identification
- Added identification of hardened container images (Chainguard, MinimOS, Docker Hardened Images, Echo).

### CLI
- Added `--max-file-size` to all artifact types.
- Added `--disable-default-file-exclusions` to disable platform-specific default exclusions.

### Inspector Scan API
- Added client-side SBOM validation before API calls (format, component count, compressed size limits).
- Improved error messages for common API errors (413, 403, 429, 500).

### Miscellaneous
- Improved handling of I/O errors during artifact pre-processing.
- Improved handling of opaque whiteout files (.wh..wh..opq) during container image pre-processing.
- Minor improvements to C# deps.json parsing.
- Some noisy console logs have been set to debug level, down from warning level.


## [1.10.1] - January 29th 2026
- Upgraded Go compiler from 1.25.5 to 1.25.6.

## [1.10.0] - December 9th 2025
- Added support for Atlassian Servers (Jira Core, Confluence) and Atlassian Applications (Jira Software, Service Desk)
- Improved inventory accuracy of compiled Go binaries that use the replace directive for packages.
- Improved error handling for ECR MANIFEST_INACCESSIBLE error types.
- Improved error handling for malformed container image configuration files.
- Upgraded golang.org/x/crypto v0.44.0 to v0.45.0.
- Upgraded go toolchain from v1.25.3 to v1.25.5.

## [1.9.1] - November 14th 2025
- Upgraded golang.org/x/crypto@v0.37.0 package to v0.44.0. 

## [1.9.0] - November 11th 2025

### Artifacts
- Added support for Windows-based container images.

### OS Support
- Added support for Microsoft Windows. Note: Windows support is experimental; we are not releasing pre-compiled Windows builds at this time. Windows builds will follow in a future release.
- Improved parsing of /etc/os-release when the OS name contains spurious single/double quotation marks.
- Improved collection of currently installed OS packages from Debian and Ubuntu.
- Added support for FreeBSD 13 and above.
- Added instance type when inventorying EC2 instances.
- Added vendor qualifier to Amazon Linux packages for non-native repository identification.

### Expanded Ecosystems
- Added support for MySQL and MariaDB installations.
- Added support for PHP interpreter installations.
- Added support for Jenkins-core installations.
- Added support for 7zip installations on Windows OS.
- Added support for Elasticsearch.
- Added support for Curl and LibCurl installations.
- Added support for Microsoft applications.

### Package Support
- Added support for Java Gradle inventory and vulnerability scanning.
- Minor improvements to mitigate infinite loops in Maven project dependency resolution.
- Resolved an issue that would sometimes cause an array index out of bounds error.
- Improved support for Node runtime on Distroless containers.

### Security
- Added mitigations against possible directory traversal threats during container image unpacking.

### Miscellaneous
- Migrated Dockerfile parsing to Moby Buildkit.
- Improved handling of Docker findings within container images built with here-documents.
- Added `--scan-sbom-endpoint` and `--scan-sbom-service` CLI arguments.
- Removed `--enable-log-to-disk option`.
- Optimize scanning performance for NPM package collectors

## [1.8.3] - November 2nd 2025
- Update go toolchain version to the latest stable version 1.25.3.

## [1.8.2] - September 5th 2025
- Improve archive unpacking to mitigate potential directory traversal.

## [1.8.1] - August 12th 2025
- Fix ScanSBOM operation failure when unable to fall back to IMDSv1 at hop limit.
- Update go toolchain version to the latest stable version 1.24.6.

## [1.8.0] - June 24th 2025
- Added support for inventorying applications that were installed outside of a package manager, i.e. compiled from source code:
    - OpenSSL
    - Nginx
    - OpenSSH
    - Oracle Database Server
- Sbomgen can now inventory Amazon EBS snapshots as mounted volumes.
- When inventorying RHEL systems, sbomgen now adds metadata for E4S/EUS subscriptions.
- Added support for inventorying SSL/TLS certificate files.
- Minor improvements to go.mod package collection.
- Sbomgen returns an unsupported OS error when attempting to inventory a Windows container image.
- Sbomgen returns 'ErrInvalidImageFormat' when attempting to unpack a container image with incorrect gzip checksum in its layers.
- Sbomgen's progress indicator has been removed to improve stability; related CLI arguments are retained for backwards compatibility.
- Sbomgen now publishes release packages hashes for integrity verification:
    - https://amazon-inspector-sbomgen.s3.amazonaws.com/latest/linux/amd64/inspector-sbomgen.zip.sha256
    - https://amazon-inspector-sbomgen.s3.amazonaws.com/latest/linux/arm64/inspector-sbomgen.zip.sha256

## [1.7.3] - June 12th 2025

- Update go toolchain version to the latest stable version 1.24.4.

## [1.7.2] - May 30th 2025

- Support new package database path in ChainGuard/Wolfi Linux images.

## [1.7.1] - May 7th 2025

- Update go toolchain version to the latest stable version 1.24.2.

## [1.7.0] - April 15th 2025

- inspector-sbomgen now collects license information; enable this feature by toggling the --collect-licenses option.
- Added support for detecting AWS secret keys in Dockerfiles.
- inspector-sbomgen now supports distroless images based on Ubuntu.
- Added support to identify RPM, APK and DPKG database tampering within Dockerfiles or container images.
- Added support for excluding pom.xml scanner in compiled Java apps and improved detection of optional dependencies.
- Added ability to include specific additional scanners beyond default scanner groups via command line option --additional-scanners.
- Added support for detecting Go Zero pseudo version format in Go module dependencies.
- Added support for Microsoft SQL server collection.
- Added support for custom console loggers when using sbomgen as a Go package.
- Improved package deduplication logic when processing a Debian-based container image with the --layers argument.
- Improved handling of out of disk errors.
- Improved error handling of corrupted container image layer.
- Improved error handling when scanning unsupported media types (Docker Image Manifest V2, Schema 1).
- Reduced disk usage when decompressing sparse files.

## [1.6.3] - February 25th 2025
- Support replace directive in go.mod.

## [1.6.2] - February 18th 2025

- Added timeout for reading RPM DB.
- Optimized container layer processing.
- Fixed RPM DB read error due to SQLITE_READONLY_DIRECTORY (1544).
- Improved validation of GoToolChain version.
- Improved JavaScript package detection logic.

## [1.6.1] - February 4th 2025

- Resolved an issue that caused excessive scan durations when analyzing Go packages in container images
- Improved deduplication logic when inventorying APK-based operating systems (Alpine, Chainguard, Wolfi)
- Add default scan path for extra-ecosystems in localhost scan
- Minor improvements to Java package scanners

## [1.6.0] - January 27th 2025

- Improved detection of Node.JS runtimes installed via 3rd party utilities.
- Reduced memory consumption when extracting large files during container scan.
- Sbomgen now collects operating system and kernel information for Bottlerocket OS.
- Improved behavior consistency when scanning container images from various sources (Docker engine, TAR, remote registry).
- Improved error messages when inspector-sbomgen is unable to download a remote image due to authentication-related issues.
- Minor improvements in JavaScript package collection.
- Improved detection of NixOS version number.
- Packages from Python requirements.txt files with non-deterministic version numbers are now included in the SBOM for completeness.
- Packages from JavaScript project root-level package.json files with non-deterministic version numbers are now included in the SBOM for completeness.
- C# packages with non-deterministic version numbers are now included in the SBOM for completeness.
- Fixed issue that caused a crash while processing PHP composer.lock packages with empty names and versions.
- Sbomgen now inventories PHP dev dependencies.
- Moved OS component from metadata section to components section.
- Support Chainguard namespace (Commercial version).
- Sbomgen now returns an explicit error, `ImageValidationFailure` / `InvalidImageFormat`, when scanning a malformed container image. Prior to this update, when scanning potentially corrupt container images, sbomgen would return an SBOM without any components.

## [1.5.5] - December 5th 2024

- Improved error handling when processing a container image with an unsupported media type for image configuration.
- Fixed an issue where some OS components are not identified with `--layers` option.
- Updated Rust dependencies component type to `library`.
- Improved OS package component handling when package name or package version is empty.

## [1.5.4] - November 25th 2024

- Improved error handling when processing a container image with an unsupported media type for layers.
- Improved error handling when processing a container image in which the layers in the image differ from the layers specified in the manifest.json file.

## [1.5.3] - November 18th 2024

- Improved error handling when container images are deleted during SBOM generation.

## [1.5.2] - November 14th 2024

- Added new errorTypes support for `MANIFEST_UNKNOWN` and `NAME_UNKNOWN`.

## [1.5.1] - November 5th 2024

- Added support for NixOS and BusyBox distributions. 
- Improved `--platform` argument to adhere to Docker standard of os/cpu. If platform is not specified, default to linux/amd64.
- Added version to operating-system components during localhost scans.
- Added development dependency qualifier to JavaScript package URLs.
- Fixed an issue where container image files were temporarily written to disk without needed read permissions.
- Improved identification of compiled Go and Rust binaries and Go toolchain.
- Improved parsing of JavaScript package names.
- Improved parsing of Go package namespaces.
- Improved parsing of package URLs.
- Updated `:kernel` property name to kernel_component.

## [1.5.0] - October 1st 2024

- Added support for scanning PHP Composer V1 files.
- Added support for scanning NodeJS `package-lock.json` v1 and v2.
- Added PhotonOS source package dependencies as nested components.
- Added additional metadata to container components: `image_arch`, `image_author`, and `image_docker_version`.
- Added support for kernel live patching on Amazon Linux.
- Added `instance_id` to metadata when scanning localhost in EC2.
- Added support for architecture when scanning images from remote registries using the `--platform` cli argument.
- Fixed an issue with duplicate properties in `rhel-rpm` components.
- Improved scanning of Go binaries.
- Improved scanning of Python `requirements.txt` files.
- Improved formatting of Javascript purls.

## [1.4.0] - August 27th 2024

- Added support for scanning `pom.xml` files in Java packages.
- Added support for scanning Wordpress installations; including plus Wordpress themes and plugins.
- Added support for scanning Yarn and PNPM projects.
- Added support for scanning Wolfi Linux.
- Added Ruby gem platform as purl qualifier.
- Added `running_kernel` property to linux kernel packages.
- Added Alpine Linux source package dependencies as nested components.
- Improved handling of Photon OS source packages.
- Improved cleanup of filesystem artifacts on panic.
- Improved the internal library API.

## [1.3.2] - July 22nd 2024

- Fixed an issue where multiple Dockerfile findings of the same type were not included in the SBOM.
- Improved container image layer processing for consistency when using Docker daemon.
- Improved console logs.

## [1.3.1] - July 15th 2024

- Added RPM source packages as purl qualifiers.
- Fixed an issue that would result in a crash when using the `--skip-files` with container images.
- Improved console messages when processing Ruby `.gemspec` files.

## [1.3.0] - July 9th 2024

- Added support for scanning zstd and bzip2 compressed archives.
- Added support for scanning Apache httpd installations.
- Added support for scanning Oracle JDK installations.
- Added support for scanning stand alone files using the `directory` cli argument.
- Improved handling of directories and relative paths when using the `directory` and `localhost` cli arguments.
- Improved processing of `Gemfile.lock` files with multi-Gem sections.
- Improved handling of whiteout files in container images.

## [1.2.1] - June 14th 2024

- Improved detection of C# packages.config files.

## [1.2.0] - June 4th 2024

- Added support for scanning standalone Dockerfiles and build history from pre-built container images for security misconfigurations.
- Added Ubuntu source package dependencies as nested components.
- Added Debian source packages as purl qualifiers.
- Added support for scanning development dependencies from `Pipfile.lock`.
- Fixed an issue with unpacking zip archives.
- Debug properties, i.e. `source_file_scanner` and `source_package_collector`, are no longer added to SBOMs by default; to display these properties, add the `--enable-debug-props` cli argument.

## [1.1.1] - April 22nd 2024

- Added `kernel_component` property to identify kernel-specific SBOM components.
- Added support for scanning module stream information in rpm-based purls.
- Fixed an issue when generating the `inspector-sbomgen` SHA-256 hash from a relative path.
- Fixed an issue when scanning container images that do not contain `/etc/os-release`, such as scratch images.
- Improved scanning of Go binaries.
- Improved scanning of Java packages.
- Updated third-party package dependencies.

## [1.1.0] - February 15th 2024

- Added support for post-processing SBOMs with Amazon Inspector using `--scan-sbom`
- Added support for scanning directories and archives (.zip, .tar, and .tar.gz).
- Added support for scanning compiled Go and Rust binaries (packed or obfuscated binaries are not supported).
- Added `operating-system` component to container SBOMs.
- Fixed an issue causing high RAM consumption on container images containing very large files.
- Updated SBOM output to use CycloneDX v1.5 tools metadata object.
