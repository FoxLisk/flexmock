import inspect
import types
import unittest


class InvalidMethodSignature(Exception):
  pass


class MethodNotCalled(Exception):
  pass


class AlreadyMocked(Exception):
  pass


class Expectation(object):
  """Holds expectations about methods.

  The information contained in the Expectation object includes method name,
  its argument list, return values, and any exceptions that the method might
  raise.
  """
  def __init__(self, name, mock, args=None, return_value=None):
    self.method = name
    self.original_method = None
    if not isinstance(args, tuple):
      self.args = (args,)
    else:
      self.args = args
    self.return_value = return_value
    self.times_called = 0
    self.expected_calls = None
    self.exception = None
    self.mock = mock

  def __str__(self):
    return '%s%s -> %s' % (self.method, self.args, self.return_value)

  def with_args(self, args):
    """Override the arguments used to match this expectation's method."""
    if not isinstance(args, tuple):
      self.args = (args,)
    else:
      self.args = args
    return self

  def and_return(self, value):
    """Override the return value of this expectation's method."""
    self.return_value = value
    return self

  def times(self, number):
    """Number of times this expectation's method is expected to be called."""
    self.expected_calls = number
    return self

  def once(self):
    """Alias for times(1)."""
    return self.times(1)

  def twice(self):
    """Alias for times(2)."""
    return self.times(2)

  def never(self):
    """Alias for times(0)."""
    return self.times(0)

  def and_raise(self, exception):
    """Specifies the exception to be raised when this expectation is met."""
    self.exception = exception
    return self

  def verify(self):
    """Verify that this expectation has been met.

    Returns:
      Boolean

    Raises:
      MethodNotCalled Exception
    """
    if not self.expected_calls:
      return True
    if self.times_called == self.expected_calls:
      return True
    else:
      raise MethodNotCalled(
          '%s expected to be called %s times, called %s times' %
          (self.method, self.expected_calls, self.times_called))

  def reset(self):
    """Returns the methods overriden by this expectation to their originals."""
    if isinstance(self.mock, FlexMock):
      return  # no need to worry about mock objects
    if inspect.isclass(self.mock):
      self.mock = FlexMock._restore_class(self.mock)
    if self.original_method:
      setattr(self.mock, self.method, self.original_method)
    elif self.method in self.mock.__dict__:
      delattr(self.mock, self.method)
    for attr in FlexMock.UPDATED_ATTRS:
      if hasattr(self.mock, attr):
        delattr(self.mock, attr)


class FlexMock(object):
  """Creates mock objects or puts existing objects or classes under mock.
  
  To create a new mock object with some attributes:
    FlexMock('some_name', attr1=value1, attr2=value2, ...)

  To put existing object under mock:
    FlexMock(some_object)

  Now you can add some expectations:

    some_object.should_receive('some_method').and_return('some_value')

    --or--

    some_object.should_receive('some_method').and_raise(some_exception)

  To generate some assertions add a times(x) expectation:

    some_object.should_receive('some_method').times(1)

    -- which is equivalent to --

    some_object.should_receive('some_method').once()

  You can also do the same thing for all instances of a class by giving the
  FlexMock constructor a class instead of an instance. It's even possible to
  override new instances created by the class constructor using the
  new_instances() method.

  Various shortcuts are supported, so:

    FlexMock(some_object, method1='foo', method='bar')

    -- is the same as --

    FlexMock(some_object)
    some_object.should_receive('method1').and_return('foo')
    some_object.should_receive('method2').and_return('bar')
  """

  UPDATED_ATTRS = ['should_receive', '_get_flexmock_expectations',
                   '_flexmock_expectations', '_mock', 'new_instances']

  def __init__(self, object_class_or_name, force=False, **kwargs):
    """FlexMock constructor.
    
    Args:
      force: Boolean, see mock() method for explanation
      kwargs: dict of attribute/value pairs used to initialize the mock object
    """
    self._flexmock_expectations_ = []
    if isinstance(object_class_or_name, str):
      self.name = object_class_or_name
      for attr, value in kwargs.items():
        setattr(self, attr, value)
      self._mock = self
    else:
      self.mock(object_class_or_name, force=force, **kwargs)
    self._update_unittest_teardown()

  def should_receive(self, method, args=None, return_value=None):
    """Adds a method Expectation to the provided class or instance.

    Args:
      method: string name of the method to add
      args: tuple of multipe args or *single* arg of any type
      return_value: whatever you want the method to return

    Returns:
      expectation: Expectation object
    """
    expectation = self._retrieve_or_create_expectation(method, args,
                                                       return_value)
    self._flexmock_expectations_.append(expectation)
    self._add_expectation_to_object(expectation, method)
    return expectation

  def new_instances(self, returns=None):
    """Overrides creation of new instances of the mocked class.

    Args:
      returns: the object that should be created instead of the default

    Returns:
      expectation: Expectation object
    """
    if inspect.isclass(self):
      self = self._convert_to_new_style(self)
    method = '__new__'
    expectation = self._retrieve_or_create_expectation(
        method, None, returns)
    self._flexmock_expectations_.append(expectation)
    if not hasattr(expectation, 'original_method'):
      expectation.original_method = getattr(self._mock, method)
    self._mock.__new__ = self.__create_new_method(returns)
    return expectation

  def mock(self, obj, force=False, **kwargs):
    """Puts the provided object or class under mock.

    This method is left public, but you probably just want to use the FlexMock
    constructor to do this rather than calling it directly.
    
    Args:
      obj: object or class to mock
      force: Boolean, override the default sanity checks and clobber existing
             methods by FlexMock methods. You probably don't want to do this.
      kwargs: dict of method name/return value pairs to generate

    Returns:
      None

    Raises:
      AlreadyMocked
    """
    for attr in self.UPDATED_ATTRS:
      if (hasattr(obj, attr)) and not force:
        raise AlreadyMocked
    obj.should_receive = self.should_receive
    obj.new_instances = self.new_instances
    obj._get_flexmock_expectations = self._get_flexmock_expectations
    obj._flexmock_expectations_ = []
    self._mock = obj
    for method, return_value in kwargs.items():
      obj.should_receive(method, return_value=return_value)

  def _update_unittest_teardown(self):
    unittest.TestCase._flexmock_expectations = self._flexmock_expectations_
    saved_teardown = unittest.TestCase.tearDown
    def unittest_teardown(self):
      for expectation in self._flexmock_expectations: 
        expectation.verify()
        expectation.reset()
      self._flexmock_expectations = []
      saved_teardown(self)
    unittest.TestCase.tearDown = unittest_teardown

  def _retrieve_or_create_expectation(self, method, args, return_value):
    if method in [x.method for x in self._flexmock_expectations_]:
      expectation = [x for x in self._flexmock_expectations_
                     if x.method == method][0]
      if expectation.args is None:
        if isinstance(args, tuple):
          expectation.args = args
        else:
          expectation.args = (args,)
      else:
        expectation = Expectation(method, self._mock, args, return_value)
    else:
      expectation = Expectation(method, self._mock, args, return_value)
    return expectation

  def _add_expectation_to_object(self, expectation, method):
    method_instance = self.__create_mock_method(method)
    if hasattr(self._mock, method):
      expectation.original_method = getattr(self._mock, method)
    setattr(self._mock, method, types.MethodType(
        method_instance, self._mock))

  def _get_flexmock_expectations(self, name=None, args=None):
    if args == None:
      args = ()
    if not isinstance(args, tuple):
      args = (args,)
    if name:
      for e in reversed(self._flexmock_expectations_):
        if e.method == name:
          if self._match_args(args, e.args):
            return e
    else:
      return self._flexmock_expectations_

  def _match_args(self, given_args, expected_args):
    if given_args == expected_args or expected_args == (None,):
      return True
    try:
      if len(given_args) == 1 and isinstance(given_args[0], expected_args[0]):
        return True
    except:
      pass

  @staticmethod
  def _convert_to_new_style(cls):
    class NewClass(cls, object): pass
    NewClass._flexmock_old_class_ = cls
    if '__new__' not in dir(cls):
      return NewClass 
    else:
      return cls

  @staticmethod
  def _restore_class(cls):
    if '_flexmock_old_class_' in dir(cls):
      return cls._flexmock_old_class_
    else:
      return cls

  def __create_mock_method(self, method):
    def mock_method(self, *kargs, **kwargs):
      arguments = kargs
      expectation = self._get_flexmock_expectations(method, arguments)
      if expectation:
        expectation.times_called += 1
        if expectation.exception:
          raise expectation.exception
        return expectation.return_value
      else:
        raise InvalidMethodSignature('%s%s' % (method, str(arguments)))
    return mock_method

  def __create_new_method(self, return_value):
    @staticmethod
    def new(cls):
      return return_value
    return new