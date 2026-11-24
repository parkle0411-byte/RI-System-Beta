// Node resolve hook for the check scripts: src modules import siblings without ".js" (Vite resolves them; plain Node does not).
export async function resolve(specifier, context, next) {
  try {
    return await next(specifier, context)
  } catch (error) {
    if (error?.code === 'ERR_MODULE_NOT_FOUND' && /^\.\.?\//.test(specifier) && !/\.[cm]?js$/.test(specifier)) {
      return next(specifier + '.js', context)
    }
    throw error
  }
}
