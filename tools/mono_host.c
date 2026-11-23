/* Run a validation executable on the Mono runtime shipped with KSP for macOS. */
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>

static void *symbol(void *library, const char *name)
{
    void *result = dlsym(library, name);
    if (!result) {
        fprintf(stderr, "%s\n", dlerror());
        exit(1);
    }
    return result;
}

int main(int argc, char **argv)
{
    if (argc < 4) return 2;
    void *library = dlopen(argv[1], RTLD_NOW | RTLD_GLOBAL);
    if (!library) {
        fprintf(stderr, "%s\n", dlerror());
        return 1;
    }
    void (*set_path)(const char *) = symbol(library, "mono_set_assemblies_path");
    void (*set_dirs)(const char *, const char *) = symbol(library, "mono_set_dirs");
    void (*parse_config)(const char *) = symbol(library, "mono_config_parse");
    void *(*init)(const char *, const char *) = symbol(library, "mono_jit_init_version");
    void *(*open_assembly)(void *, const char *) = symbol(library, "mono_domain_assembly_open");
    int (*run)(void *, void *, int, char **) = symbol(library, "mono_jit_exec");
    void (*cleanup)(void *) = symbol(library, "mono_jit_cleanup");
    set_path(argv[3]);
    set_dirs(argv[3], argv[3]);
    parse_config(NULL);
    void *domain = init("KSP configuration validation", "v4.0.30319");
    void *assembly = open_assembly(domain, argv[2]);
    if (!assembly) return 1;
    int result = run(domain, assembly, argc - 2, argv + 2);
    cleanup(domain);
    return result;
}
